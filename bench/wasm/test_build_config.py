#!/usr/bin/env python3
"""Check the real make dependency graph with recording compiler stand-ins."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BuildConfiguration(unittest.TestCase):
    def test_configuration_changes_recompile_all_compiler_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src = root / 'emu'
            shutil.copytree(ROOT / 'emu', src, ignore=shutil.ignore_patterns(
                '*.o', 'picat', '*.js', '*.wasm', '.emscripten-build-config*'))
            bindir = root / 'bin'
            bindir.mkdir()
            compiler = '''#!/usr/bin/env python3
import json, pathlib, sys
with open('calls.jsonl', 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
a = sys.argv[1:]
out = a[a.index('-o')+1] if '-o' in a else pathlib.Path(a[-1]).with_suffix('.o').name
pathlib.Path(out).touch()
'''
            for name in ['emcc', 'em++']:
                p = bindir / name
                p.write_text(compiler)
                p.chmod(0o755)
            env = dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'])
            targets = ['dis.o', 'black_white.o', 'kis_allocate.o', 'fann_interface.o']

            def make(simd):
                before = len(calls())
                subprocess.run(['make', '-f', 'Makefile.emscripten', 'SIMD='+simd,
                                *targets], cwd=src, env=env, check=True,
                               capture_output=True, text=True)
                return calls()[before:]

            def calls():
                p = src / 'calls.jsonl'
                return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

            for simd in ['0', '1', '0']:
                changed = make(simd)
                self.assertEqual(len(changed), 4)
                self.assertTrue(all(('-msimd128' in a) == (simd == '1') for a in changed))
                self.assertEqual(make(simd), [])
            for invalid in ['2', '', '0 1']:
                p = subprocess.run(['make', '-f', 'Makefile.emscripten', 'SIMD='+invalid],
                                   cwd=src, env=env, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('SIMD must be 0 or 1', p.stderr)


if __name__ == '__main__':
    unittest.main()
