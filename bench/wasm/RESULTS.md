# SIMD experiment — 2026-11-14

Enabling SIMD produced real vector instructions but **no consistent overall speedup** in these workloads. Keep it opt-in. The results do not justify enabling SIMD by default or adding handwritten SIMD to the interpreter without profiling.

## Setup

- Base: `2d00e3a456c2f7736940e1a1ed66e7b0aef8e021`; identical engine, headers, and solver sources in both builds.
- Emscripten 4.0.21; engine `-O2`, Espresso/Kissat `-O3`, no LTO, fast-math, or relaxed SIMD. The only compiler difference is `-msimd128`.
- Node v24.22.1, V8 13.6.233.17-node.58; Linux x86_64; INTEL(R) XEON(R) PLATINUM 8573C. Shared cloud host, no CPU pinning or frequency control.
- NODERAWFS enabled equally in both measured builds. Runtime validation is under Node; browsers, workers, ARM, and macOS/Nix were not benchmarked.
- Two serial sessions, nine randomized paired rounds each: 216 successful process invocations total. Session 1 warmed each workload twice; session 2 warmed one full batch (minimum two iterations). No compilation ran concurrently with the timing sessions; normal shared-host interference and occasional development activity were not isolated.
- Workload times include their correctness assertions. Warmed timings use high-resolution Node timestamps around synchronous stdout markers, excluding process startup, WASM/Picat loading, and warmup. Picat CPU-time statistics returned zero in this SDK and were rejected as a timer.

## Session 2: warmed work

Times are milliseconds per iteration. MAD is median absolute deviation. Speedup is scalar median / SIMD median; above 1 favors SIMD. Each value summarizes nine fresh-process samples, with a warmed loop inside each process.

| Workload | Scalar median ± MAD (range) | SIMD median ± MAD (range) | Speedup |
|---|---:|---:|---:|
| cp-queens-100 | 59.049 ± 3.728 (55.320–81.192) | 67.577 ± 7.861 (52.369–97.508) | 0.874× |
| sat-queens-50 | 692.904 ± 18.537 (663.645–786.621) | 694.628 ± 32.612 (643.369–754.513) | 0.998× |
| cp-sudoku-9 | 1.388 ± 0.078 (1.269–1.604) | 1.397 ± 0.033 (1.270–1.829) | 0.993× |
| integer-loop | 65.343 ± 0.471 (64.845–72.114) | 63.757 ± 0.908 (62.849–71.056) | 1.025× |
| sort-list | 45.443 ± 0.509 (44.035–49.848) | 46.373 ± 1.364 (44.678–49.935) | 0.980× |

Session 2 warmup/measured iteration counts are 2/2 for CP queens, 3/3 for SAT queens, 100/100 for Sudoku, and 5/5 for integer loops and sorting. Integer-loop iterations each perform one million modular additions; sorting iterations sort 100,000 deterministic integers.

## Startup and complete process costs

Fresh-process arithmetic is startup-dominated, not an isolated compile timer and not a cold filesystem-cache measurement. Workload process times include warmup and all measured iterations, so they are not per-operation timings.

| Workload | Scalar process median (ms) | SIMD process median (ms) |
|---|---:|---:|
| startup | 339.14 | 347.98 |
| cp-queens-100 | 397.12 | 461.04 |
| sat-queens-50 | 4353.75 | 4368.18 |
| cp-sudoku-9 | 408.39 | 429.64 |
| integer-loop | 791.11 | 800.07 |
| sort-list | 643.88 | 664.91 |

Startup ranges were 297.7–434.0 ms scalar and 293.1–453.7 ms SIMD. These variations exceed the difference between the startup medians.

## Warmup sensitivity and interpretation

| Workload | Session 1 speedup (two warmups) | Session 2 speedup (full warmup batch) |
|---|---:|---:|
| cp-queens-100 | 1.001× | 0.874× |
| sat-queens-50 | 0.987× | 0.998× |
| cp-sudoku-9 | 0.742× | 0.993× |
| integer-loop | 0.996× | 1.025× |
| sort-list | 0.994× | 0.980× |

The apparent Sudoku slowdown after two warmups disappears with a full warmup batch. CP queens varies substantially between sessions. Integer loops improve slightly only in the second session. Consequently, neither a reliable general speedup nor a stable regression for all programs is established. These warmed measurements are not proof of fully converged JIT steady state; more runs on target browsers/hardware and profiling of hot functions are needed before choosing specialized intrinsics.

## Emission and artifact sizes

| Artifact / metric | Scalar | SIMD | Change |
|---|---:|---:|---:|
| WASM bytes | 4,135,357 | 4,150,963 | +15,606 (+0.38%) |
| WASM gzip bytes | 962,340 | 969,019 | +6,679 (+0.69%) |
| JavaScript bytes | 83,888 | 83,888 | +0 (+0.00%) |
| Actual SIMD instructions in final disassembly | 0 | 1521 | — |

Binaryen disassembly shows instructions such as `v128.load/store`, `i32x4.add`, and `i8x16.shuffle`. This is opcode evidence, not merely a target-feature flag. Object inspection also finds vector operations in the interpreter and FANN. Static counts do not show how often a benchmark executes those instructions. JavaScript size above excludes the identical benchmark timing hook.

## Validation and evidence

- Both real scalar and SIMD builds succeeded. Every timed invocation passed its workload correctness checks. All generated workloads also passed against native Picat before timing changes.
- The default embeddable SIMD link (web/worker/node, without NODERAWFS) passed a Node smoke test writing a Picat program through `Module.FS` and invoking it through `Module.callMain` (output `42`). Actual browser/worker execution is untested.
- `python3 bench/wasm/test_build_config.py` passed: engine, Espresso, Kissat, and FANN rebuild on scalar → SIMD → scalar changes; unchanged configurations do not recompile; invalid switch values are rejected.
- Compiler warnings in existing upstream sources remain. No native runtime implementation was changed.
- [Session 2 raw results, metadata, hashes, opcodes and summaries](results-2026-11-14.json).
- [Session 1 raw samples](first-run-2026-11-14.csv).
- [Reproduction instructions and measurement limitations](README.md).
