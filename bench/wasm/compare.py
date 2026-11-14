#!/usr/bin/env python3
"""Build and compare scalar/SIMD Picat with isolated, identical configurations."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
LFLAGS = ('-lm -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=128MB -sSTACK_SIZE=8MB '
          '-sEXIT_RUNTIME=1 -sENVIRONMENT=node -sEXPORTED_RUNTIME_METHODS=FS,callMain '
          '-sAUTO_NATIVE_LIBRARIES=0 -sNO_DISABLE_EXCEPTION_CATCHING -sNODERAWFS=1')


def run(args, **kw):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kw).stdout


def write_workloads(out):
    workloads = {}
    for solver, n, repeats in [('cp', 100, 2), ('sat', 50, 3)]:
        src = (ROOT / f'exs/{solver}/queens.pi').read_text()
        src = src.replace('main => top.', '').replace('top =>\n    queens(100).', '')
        src = src.replace('writeln(Qs).', '''foreach(I in 1..N-1, J in I+1..N)
        if Qs[I] == Qs[J]; abs(Qs[I]-Qs[J]) == J-I then
            throw(invalid_queens)
        end
    end.''')
        workloads[f'{solver}-queens-{n}'] = (src, f'queens({n})', repeats)
    src = (ROOT / 'exs/cp/sudoku.pi').read_text().split('/*')[0]
    src = src.replace('main => top.', '').replace('top => \n    sudoku.', '')
    src = src.replace('writeln(M),', '')
    src = src.replace('foreach(I in 1..N) writeln(A[I]) end.', '''foreach(I in 1..N)
        if sort(remove_dups(A[I].to_list())) != 1..N then throw(invalid_row) end,
        if sort(remove_dups([A[J,I] : J in 1..N])) != 1..N then throw(invalid_column) end
    end,
    foreach(R in 1..M..(N-M+1), C in 1..M..(N-M+1))
        if sort(remove_dups([A[R+D,C+E] : D in 0..M-1, E in 0..M-1])) != 1..N then
            throw(invalid_box)
        end
    end.''')
    workloads['cp-sudoku-9'] = (src, 'sudoku', 100)
    workloads['integer-loop'] = ('''task =>
    S = 0,
    foreach(I in 1..1000000) S := (S+I) mod 1000003 end,
    if S != 3 then throw(invalid_sum) end.
''', 'task', 5)
    workloads['sort-list'] = ('''task =>
    L = [(I*7919) mod 100003 : I in 1..100000],
    S = sort(L),
    if len(S) != 100000; sum(S) != 5000073754 then throw(invalid_sort) end,
    check_order(S).
check_order([X,Y|Xs]) =>
    if X > Y then throw(invalid_order) end,
    check_order([Y|Xs]).
check_order(_) => true.
''', 'task', 5)
    for name, (src, goal, repeats) in workloads.items():
        # Warm up inside each fresh process; measured loop excludes loading and
        # one full warmup batch, but is not a guarantee of full JIT convergence.
        src += f'''\nmain =>
    foreach(_ in 1..{max(2, repeats)}) {goal} end,
    writef("BENCH_START%n"),
    foreach(_ in 1..{repeats}) {goal} end,
    writef("BENCH_END {name}%n").
'''
        (out / f'{name}.pi').write_text(src)
    return {name: n for name, (_, _, n) in workloads.items()}


def build(out, jobs):
    for name, simd in [('scalar', '0'), ('simd', '1')]:
        dest = out / name
        dest.mkdir()
        # Only tracked sources, never native or previous WASM object files.
        files = run(['git', '-C', str(ROOT), 'ls-files', 'emu']).splitlines()
        for f in files:
            target = dest / Path(f).relative_to('emu')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, target)
        with (out / f'{name}-build.log').open('w') as log:
            subprocess.run(['make', '-f', 'Makefile.emscripten', f'-j{jobs}',
                            f'SIMD={simd}', f'LFLAGS={LFLAGS}'], cwd=dest,
                           stdout=log, stderr=subprocess.STDOUT, check=True)


def describe_artifact(out, name, disassembler):
    wasm = out / name / 'picat.wasm'
    wat = run([disassembler, str(wasm)])
    # Count actual instruction forms in disassembly, not target_features metadata.
    ops = collections.Counter(re.findall(r'\((v128\.[\w.]+|[if](?:8x16|16x8|32x4|64x2)\.[\w.]+)', wat))
    data = wasm.read_bytes()
    js = (out / name / 'picat.js').read_bytes()
    return dict(wasm_bytes=len(data), wasm_gzip_bytes=len(gzip.compress(data, mtime=0)),
                js_bytes=len(js), sha256=hashlib.sha256(data).hexdigest(),
                simd_instruction_count=sum(ops.values()), simd_opcodes=dict(ops))


def summarize(values):
    med = statistics.median(values)
    return dict(median=med, min=min(values), max=max(values),
                mad=statistics.median(abs(v-med) for v in values))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True, help='New directory outside the source tree')
    ap.add_argument('--rounds', type=int, default=9)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--node', default='node')
    ap.add_argument('--wasm-dis', default='wasm-dis')
    ap.add_argument('--reuse', action='store_true', help='Reuse builds for another measurement session')
    args = ap.parse_args()
    if args.rounds < 3:
        ap.error('--rounds must be at least 3')
    out = args.out.resolve()
    if not args.reuse:
        out.mkdir(parents=True, exist_ok=False)
        build(out, args.jobs)
    workloads = write_workloads(out)
    result = dict(platform=platform.platform(), cpu=next((x.split(':', 1)[1].strip()
        for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown')
        if Path('/proc/cpuinfo').exists() else platform.processor(),
        node=run([args.node, '--version']).strip(),
        v8=run([args.node, '-p', 'process.versions.v8']).strip(),
        emcc=run(['emcc', '--version']).splitlines()[0],
        source_commit=run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).strip(),
        source_diff_sha256=hashlib.sha256(run(['git', '-C', str(ROOT), 'diff', 'HEAD']).encode()).hexdigest(),
        link_flags=LFLAGS, rounds=args.rounds, warmups_per_process={name: max(2, n) for name, n in workloads.items()},
        iterations=workloads, artifacts={}, samples=[], summary={})
    for variant in ['scalar', 'simd']:
        result['artifacts'][variant] = describe_artifact(out, variant, args.wasm_dis)
    assert result['artifacts']['scalar']['simd_instruction_count'] == 0
    assert result['artifacts']['simd']['simd_instruction_count'] > 0
    # NODERAWFS bypasses Module.print; observe its synchronous stdout writes.
    # Picat's getrusage-based statistics(runtime) returns zero under this SDK.
    # This JS-only harness leaves the measured WASM binaries untouched.
    prelude = """var benchFS = require('fs');
var benchWrite = benchFS.writeSync.bind(benchFS), benchPending = '', benchStart;
benchFS.writeSync = function(fd, data, offset, length, position) {
  if (fd !== 1) return benchWrite.apply(null, arguments);
  var chunk = typeof data === 'string' ? data : Buffer.from(data.buffer, data.byteOffset + offset, length).toString('utf8');
  benchPending += chunk;
  var newline;
  while ((newline = benchPending.indexOf('\\n')) !== -1) {
    var line = benchPending.slice(0, newline);
    benchPending = benchPending.slice(newline + 1);
    if (line === 'BENCH_START') benchStart = process.hrtime.bigint();
    else if (line.startsWith('BENCH_END ')) {
      var elapsed = Number(process.hrtime.bigint() - benchStart) / 1e6;
      benchWrite(1, Buffer.from(line.replace('BENCH_END ', 'BENCH ') + ' ' + elapsed + '\\n'));
    } else benchWrite(1, Buffer.from(line + '\\n'));
  }
  return typeof data === 'string' ? Buffer.byteLength(data) : length;
};
"""
    for variant in ['scalar', 'simd']:
        original = out / variant / 'picat.js'
        (out / variant / 'picat-timed.js').write_text(prelude + original.read_text())
    rng = random.Random(1729)
    for round_number in range(args.rounds):
        names = ['startup'] + list(workloads)
        rng.shuffle(names)
        for name in names:
            variants = ['scalar', 'simd']
            rng.shuffle(variants)
            for variant in variants:
                argv = [args.node, str(out / variant / 'picat-timed.js')]
                argv += ['-g', 'println(1+2)'] if name == 'startup' else [str(out / f'{name}.pi')]
                start = time.perf_counter()
                stdout = run(argv, timeout=180)
                elapsed = (time.perf_counter()-start)*1000
                if name == 'startup':
                    assert stdout.strip() == '3', stdout
                    inner = None
                else:
                    match = re.fullmatch(rf'BENCH {re.escape(name)} ([0-9.]+)\s*', stdout)
                    assert match, stdout
                    inner = float(match[1])/workloads[name]
                    assert inner > 0, 'Timer did not advance'
                sample = dict(round=round_number, workload=name, variant=variant,
                              process_ms=elapsed, warmed_iteration_ms=inner)
                result['samples'].append(sample)
                (out / 'results.json').write_text(json.dumps(result, indent=2)+'\n')
                print(json.dumps(sample), flush=True)
    for name in ['startup'] + list(workloads):
        summary = {}
        for metric in ['process_ms', 'warmed_iteration_ms']:
            if name == 'startup' and metric == 'warmed_iteration_ms':
                continue
            summary[metric] = {v: summarize([s[metric] for s in result['samples']
                if s['variant'] == v and s['workload'] == name]) for v in ['scalar', 'simd']}
            summary[metric]['median_speedup'] = summary[metric]['scalar']['median']/summary[metric]['simd']['median']
        result['summary'][name] = summary
    (out / 'results.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
