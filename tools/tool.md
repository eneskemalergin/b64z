# Local Peer Tools

Status: **Active** (last updated: 2026-09-23)

## Purpose

`tools/` contains peer selection, build rules, and small adapters used by Base64 comparisons. A timed command must run the selected peer directly. It must not add file copies, shell pipelines, logging, checksums, compression, or text conversion.

Every peer receives the same raw input files and writes Base64 bytes to stdout. Keep a peer in speed comparisons only after its output matches the valid fixture bytes. A peer that accepts a wider invalid-input grammar remains a documented compatibility difference, not a failed speed row.

## Selected peers

`peer_config.py` owns executable names, command arguments, mode coverage, and the version strings printed in retained reports. This file records why each peer is selected and how its adapter is built.

### Aklomp Base64

- Source: [aklomp/base64](https://github.com/aklomp/base64)
- Language: C99
- Selection: SIMD stream codec with runtime x86 selection and a standalone `base64` utility.
- Checkout: upstream `master`; record the selected commit in `peer_config.py` before compiling.
- Build: `AVX2_CFLAGS=-mavx2 make`; the executable uses upstream runtime CPU selection.
- Executable: the locally built Aklomp command.
- Encode command: `--wrap=0 INPUT`.
- Decode command: `--decode --no-strip-newlines INPUT`.
- Difference: its decoder accepts some noncanonical inputs that B64Z rejects.

This is the external byte reference for canonical valid inputs and the first C SIMD peer.

### simdutf `fastbase64`

- Source: [simdutf/simdutf](https://github.com/simdutf/simdutf)
- Language: C++17.
- Selection: the project ships a dedicated `fastbase64` command and documents SIMD paths across x86, ARM, POWER, RISC-V, and other targets.
- Build: Release CMake build with the upstream CPU dispatch, followed by a small C++ adapter linked to the simdutf Base64 library.
- Executable: the locally built simdutf command.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Adapter source: `tools/wrappers/simdutf_base64.cpp`.
- Adapter reason: the upstream utility appends a newline after encoded output. The retained binary calls the same simdutf library directly so stdout contains only Base64 bytes and the file boundary does not add a formatting write.
- Difference: its decoder is WHATWG-forgiving and is checked only against valid canonical inputs in the peer runner.

### GNU Coreutils `base64`

- Source: [GNU Coreutils](https://www.gnu.org/software/coreutils/)
- Language: C.
- Selection: common utility baseline with a separate encode/decode executable and predictable file arguments.
- Build: Release source build with `configure` and `make`; the generated release files included in the source tarball are used because this host does not have the archive's maintainer tools (`aclocal-1.18`, `autoconf`, and `automake-1.18`).
- Executable: the locally built GNU Coreutils command.
- Encode command: `-w 0 INPUT`.
- Decode command: `--decode INPUT`.
- Difference: GNU decoding is more permissive than B64Z decoding.
- License: GPLv3.

### Turbo-Base64

- Source: [powturbo/Turbo-Base64](https://github.com/powturbo/Turbo-Base64)
- Language: C with C++ headers.
- Selection: a fast SIMD implementation with scalar, SSE, AVX2, AVX512, NEON, and Altivec paths.
- Build: the upstream `make -f makefile` target plus a small file adapter around `tb64enc` and `tb64dec`.
- Executable: the locally built Turbo-Base64 command.
- Adapter source: `tools/wrappers/turbo_base64.c`.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Difference: the upstream API reports `0` for an empty decode and has its own error rules. Use it for valid-byte throughput after qualification, not as the strict invalid-input reference.
- License: GPLv3 with a commercial license path.

### Rust `base64`

- Source: [marshallpierce/rust-base64](https://github.com/marshallpierce/rust-base64)
- Language: Rust.
- Selection: current crate release with the `Simd` engine, which selects AVX2 on x86-64 and NEON on AArch64 at runtime before falling back to the scalar engine.
- Build: Cargo `--release` with fat LTO, one codegen unit, and the crate's default runtime SIMD detection.
- Executable: the locally built Rust base64 command.
- Adapter: a direct file-to-stdout wrapper that allocates an initialized output vector and uses the crate slice APIs for memory mode.

### Rust `base64-simd`

- Source: [Nugine/simd](https://github.com/Nugine/simd)
- Language: Rust.
- Selection: SIMD Base64 crate with default runtime feature detection.
- Build: Cargo `--release` with fat LTO, one codegen unit, and default `detect`, `std`, and `alloc` features.
- Executable: the locally built Rust base64-simd command.
- Adapter: a direct file-to-stdout wrapper using preallocated `encode` and `decode` output slices.

The first Rust row measures the current SIMD engine in the widely used general crate. The second measures a focused SIMD crate with a different allocation API.

### Zig `std.base64`

- Source: the Zig standard library installed for this repository.
- Language: Zig.
- Selection: standard-library reference peer, not a second copy of B64Z.
- Build: `zig build-exe -O ReleaseFast -mcpu=native` for the local adapter.
- Executable: the locally built Zig standard-library command.
- Adapter: a direct file-to-stdout wrapper around `std.base64.standard`.
- Difference: standard-library padding and error behavior are recorded separately from B64Z strict behavior.

## Adapter source

```text
tools/
  base64_data.py               fixture and benchmark data generator
  peer_config.py               peer commands, versions, and mode coverage
  wrappers/                    small source adapters
    rust_base64/
    rust_base64_simd/
    simdutf_base64.cpp
    zig_std_base64.zig
    turbo_base64.c
  tool.md                      peer choices and build rules
```

The adapter source files listed above are tracked so their file I/O and allocation rules can be reviewed.

Each Rust adapter has one `Cargo.toml` and one Cargo-generated `Cargo.lock` because Cargo needs package metadata and locked dependency versions. The lock files' registry checksums belong to Cargo dependency resolution.

## Local checks

```sh
python3 tools/base64_data.py generate
bash bench/linux-x86-avx2/run.sh --skip-benchmarks --skip-report
bash bench/linux-x86-scalar/run.sh --skip-benchmarks --skip-report
```

The generator recreates local valid and invalid fixtures and benchmark inputs. Each target command builds B64Z, then checks all B64Z modes, invalid-input errors, Aklomp, and every selected peer against the benchmark inputs without running timings.

The peer commands write directly to redirected stdout. The verifier passes argument arrays and compares output files byte for byte; it does not use shell pipelines, hashes, or text conversion.

On the ten small malformed fixtures, Aklomp accepted `missing-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `single-character`; simdutf accepted `missing-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `whitespace`; Coreutils accepted `missing-padding` and `whitespace`; Turbo-Base64 accepted `internal-padding`, `invalid-character`, `misplaced-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `url-safe-alphabet`; Rust `base64`, Rust `base64-simd`, and Zig `std.base64` rejected all ten. All selected peers rejected both AVX2-sized competing-error fixtures. These results describe the current executables and do not change the valid-byte checks.

## Build and qualification rules

1. Record the upstream version or commit before compiling.
2. Build ReleaseFast or the upstream release configuration. Do not time Debug binaries.
3. Use direct file arguments. Do not run `cat`, `dd`, shell substitutions, compression, decompression, or a second process in the timed command.
4. Write raw output directly to stdout. The peer runner redirects stdout to its comparison file.
5. Keep diagnostics on stderr and keep normal stdout byte-clean.
6. Qualify encode and decode bytes against canonical valid inputs before measuring speed.
7. Run the same benchmark input through every peer selected for that mode. The report records the mode, input path, build mode, compiler, CPU target, source version, and accepted-input differences.
8. Do not compare a peer's malformed-input behavior as a speed row unless its accepted grammar is the same as B64Z's grammar.
9. Strip retained peer executables after building.

Each benchmark target uses a peer only after its byte checks pass. Each report records the command label, input size, build flags, CPU target, source version, and output comparison.

`tools/base64_data.py` creates local fixture and benchmark inputs. The benchmark runner is the only peer byte verifier; external tools stay outside the Zig test executables.

## Benchmark runner

[`bench/README.md`](../bench/README.md) owns the input sets, commands, timing method, and report fields. `bench/run.sh` delegates target selection and the B64Z build settings to `bench/report.py`.

```sh
bash bench/linux-x86-avx2/run.sh
bash bench/linux-x86-scalar/run.sh
```

## Mode qualification

The current peer executables have this mode coverage:

| Peer               | Memory suites     | Streaming suites  | How it is run                                                              |
| ------------------ | ----------------- | ----------------- | -------------------------------------------------------------------------- |
| Aklomp             | no                | encode and decode | Upstream CLI uses Aklomp stateful stream functions.                        |
| simdutf            | encode and decode | no                | Direct adapter calls the library slice functions with preallocated output. |
| GNU Coreutils      | no                | encode and decode | Upstream `base64` command processes input in chunks.                       |
| Turbo-Base64       | encode and decode | no                | Direct adapter calls the library buffer functions.                         |
| Rust `base64`      | encode and decode | no                | Direct adapter calls the crate slice functions with preallocated output.   |
| Rust `base64-simd` | encode and decode | no                | Direct adapter calls the crate slice functions with preallocated output.   |
| Zig `std.base64`   | encode and decode | no                | Direct adapter calls `std.base64.standard` slice functions.                |

Aklomp and GNU Coreutils may expose whole-buffer library functions, but their selected binaries are streaming commands, so they are not placed in the memory suites. Adding a memory adapter is a separate benchmark target and requires its own release build and byte qualification. The current memory wrappers are not reused in streaming suites.

## Excluded from the default peer set

- [lemire/fastbase64](https://github.com/lemire/fastbase64) is archived and its README directs users to simdutf.
- [WojciechMula/base64simd](https://github.com/WojciechMula/base64simd) documents that its encoder and decoder do not process standard Base64 tails or `=` padding, so it cannot qualify against the valid fixture corpus without a separate full-group throughput row.
- OpenSSL, Python, Node.js, and language runtime commands add a different process or library boundary than the selected file utilities. Add them only as explicitly labelled application baselines.
