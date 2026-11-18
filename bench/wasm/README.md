# WebAssembly SIMD comparison

`compare.py` builds two clean copies of the tracked `emu/` sources with the
same Emscripten toolchain and flags. The sole compiler difference is
`SIMD=0` versus `SIMD=1` (`-msimd128`). Both use NODERAWFS for loading the same
Picat programs under Node. Engine sources keep the existing `-O2`; Espresso
and Kissat keep the existing `-O3`. No fast-math, relaxed SIMD, LTO, or altered
solver options are introduced.

After activating an Emscripten SDK with `emcc`, `em++`, and Node on PATH:

```sh
python3 bench/wasm/compare.py --out /tmp/picat-simd-run --rounds 9 \
  --wasm-dis "$EMSDK/upstream/bin/wasm-dis"
```

The output directory must be new, outside the source tree. The script records
build logs, generated `.pi` workloads, binaries, sizes, actual SIMD opcode
counts from disassembly, runtime/toolchain versions, raw samples, and median,
range, and median absolute deviation (MAD) in `results.json`. Use `--reuse`
with that directory to repeat timing without rebuilding; this overwrites the
previous results. Preserve results first if comparing sessions. The Python
script requires only the standard library, plus Git, Make, Emscripten, Node,
and Binaryen's `wasm-dis`.

Correctness checks run on every measured invocation: arithmetic must produce
3; queen placements must have no row or diagonal collisions; Sudoku rows,
columns, and boxes must contain 1–9; integer accumulation must match its known
modular sum; sorted lists must have the expected length/checksum and order.
The solver examples retain their original variable domains and Sudoku givens.
Exceptions, malformed output, and process failures stop the experiment.
Scalar disassembly must contain zero SIMD instructions and SIMD disassembly
must contain at least one. Counting opcodes does **not** establish that a
particular workload executes those instructions.

Timing is serial, with deterministic randomized workload and variant order in
each round. Each invocation starts a fresh Node process. `process_ms` includes
process startup, reading/compiling/instantiating WASM, loading/compiling Picat,
one warmup batch (at least two iterations, otherwise as many as the measured batch), measured work, and shutdown. The `startup` workload is
just `println(1+2)` and measures a startup-dominated end-to-end cost, not an
isolated WASM compile timer or a cold filesystem cache.

`warmed_iteration_ms` uses Node's monotonic `process.hrtime.bigint()` clock in
synchronous NODERAWFS stdout writes around the inner loop, divided by its
iteration count. A JS harness prepends the same stdout timing hook to each launcher;
the measured WASM binaries are unmodified. Picat's `getrusage`-based
`statistics(runtime, ...)` returned zero with this SDK and is not used. It excludes startup, Picat compilation,
and the initial warmup batch. Treat this as a warmed-work estimate, **not proof
of fully converged JIT steady state**. GC and further JIT compilation can occur
inside the measurement. Samples run in a shared cloud environment; use ranges
and MAD, repeat on target hardware, and do not infer a speedup from tiny median
differences. A ratio above 1 means SIMD was faster. These are selected
workloads, not a complete correctness or performance suite.

Check configuration switching without a compiler installation:

```sh
python3 bench/wasm/test_build_config.py
```

This runs the repository's real make dependency graph with recording compiler
stand-ins for engine, Espresso, Kissat, and FANN objects. It verifies rebuilds
for scalar → SIMD → scalar, no recompiles for unchanged flags, and rejection
of invalid switch values. It complements, rather than replaces, real builds.
