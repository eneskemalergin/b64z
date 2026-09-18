# Local Peer Tools

Status: **Active** (last updated: 2026-09-19)

## Purpose

`tools/` contains locally built peer executables used by Base64 comparisons. The source checkouts, build directories, Rust target directories, and binaries are ignored by design. They must not add file copies, shell pipelines, logging, checksums, compression, or text conversion to a timed job.

Every peer receives the same raw input files and writes Base64 bytes to stdout. Keep a peer in speed comparisons only after its output matches the valid fixture bytes. A peer that accepts a wider invalid-input grammar remains a documented compatibility difference, not a failed speed row.

## Selected peers

### Aklomp Base64

- Source: [aklomp/base64](https://github.com/aklomp/base64)
- Language: C99
- Selection: SIMD stream codec with runtime x86 selection and a standalone `base64` utility.
- Checkout: current upstream `master`, with the commit recorded by `git rev-parse` when built.
- Build: the upstream `make` target.
- Binary: `tools/bin/aklomp-base64`.
- Encode command: `--wrap=0 INPUT`.
- Decode command: `--decode --no-strip-newlines INPUT`.
- Built commit: `bf058e571ac5002b75b03fed38e33ed4e8d45eff`.
- Difference: its decoder accepts some noncanonical inputs that B64Z rejects.

This is the external byte reference for canonical valid inputs and the first C SIMD peer.

### simdutf `fastbase64`

- Source: [simdutf/simdutf](https://github.com/simdutf/simdutf)
- Version: `v9.2.0`, the current upstream release tag found during research.
- Built commit: `8abc1d7a466bc882c2d72e1effd8661492db257c`.
- Language: C++17.
- Selection: the project ships a dedicated `fastbase64` command and documents SIMD paths across x86, ARM, POWER, RISC-V, and other targets.
- Build: Release CMake build with the upstream CPU dispatch, followed by a small C++ adapter linked to the simdutf Base64 library.
- Binary: `tools/bin/simdutf-fastbase64`.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Adapter source: `tools/wrappers/simdutf_base64.cpp`.
- Adapter reason: the upstream utility appends a newline after encoded output. The retained binary calls the same simdutf library directly so stdout contains only Base64 bytes and the file boundary does not add a formatting write.
- Difference: its decoder is WHATWG-forgiving and is checked only against valid canonical inputs in the peer runner.

### GNU Coreutils `base64`

- Source: [GNU Coreutils](https://www.gnu.org/software/coreutils/)
- Version: `9.11`, the newest stable tarball listed by the GNU download server during research.
- Language: C.
- Selection: common utility baseline with a separate encode/decode executable and predictable file arguments.
- Build: Release source build with `configure` and `make`; the generated release files included in the source tarball are used because this host does not have the archive's maintainer tools (`aclocal-1.18`, `autoconf`, and `automake-1.18`).
- Binary: `tools/bin/coreutils-base64`.
- Encode command: `-w 0 INPUT`.
- Decode command: `--decode INPUT`.
- Difference: GNU decoding is more permissive than B64Z decoding.
- License note: GPLv3; keep this binary under ignored local tool paths.

### Turbo-Base64

- Source: [powturbo/Turbo-Base64](https://github.com/powturbo/Turbo-Base64)
- Version: current upstream `master`, commit `d9e584363280055ba6355938a48dc3711183f50f` from 2026-06-28.
- Language: C with C++ headers.
- Selection: a fast SIMD implementation with scalar, SSE, AVX2, AVX512, NEON, and Altivec paths.
- Build: the upstream `make -f makefile` target plus a small file adapter around `tb64enc` and `tb64dec`.
- Binary: `tools/bin/turbo-base64`.
- Adapter source: `tools/wrappers/turbo_base64.c`.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Difference: the upstream API reports `0` for an empty decode and has its own error rules. Use it for valid-byte throughput after qualification, not as the strict invalid-input reference.
- License note: GPLv3 with a commercial license path; keep this binary under ignored local tool paths.

### Rust `base64`

- Source: [marshallpierce/rust-base64](https://github.com/marshallpierce/rust-base64)
- Version: crate `0.23.1`.
- Language: Rust.
- Selection: current crate release with the `Simd` engine, which selects AVX2 on x86-64 and NEON on AArch64 at runtime before falling back to the scalar engine.
- Build: Cargo `--release` with fat LTO, one codegen unit, and the crate's default runtime SIMD detection.
- Binary: `tools/bin/rust-base64-simd`.
- Adapter: a direct file-to-stdout wrapper that uses the preallocated slice APIs for memory mode.

### Rust `base64-simd`

- Source: [Nugine/simd](https://github.com/Nugine/simd)
- Version: crate `0.8.0`, the current published release found during research.
- Language: Rust.
- Selection: SIMD Base64 crate with default runtime feature detection.
- Build: Cargo `--release` with fat LTO, one codegen unit, and default `detect`, `std`, and `alloc` features.
- Binary: `tools/bin/rust-base64-simd-crate`.
- Adapter: a direct file-to-stdout wrapper using preallocated `encode` and `decode` output slices.

The first Rust row measures the current SIMD engine in the widely used general crate. The second measures a focused SIMD crate with a different allocation API.

### Zig `std.base64`

- Source: the Zig 0.16.0 standard library installed for this repository.
- Language: Zig.
- Selection: standard-library reference peer, not a second copy of B64Z.
- Build: `zig build-exe -O ReleaseFast -Dcpu=native` for the local adapter.
- Binary: `tools/bin/zig-std-base64`.
- Adapter: a direct file-to-stdout wrapper around `std.base64.standard`.
- Difference: standard-library padding and error behavior are recorded separately from B64Z strict behavior.

## Build locations

```text
tools/
  bin/                         local peer executables
  build/                       C and C++ build trees
  src/                         upstream source checkouts
  base64_data.py               fixture and benchmark data generator
  peer_check.py                fixture and benchmark byte checks for all peers
  wrappers/                    small source adapters
    rust_base64/
    rust_base64_simd/
    simdutf_base64.cpp
    zig_std_base64.zig
    turbo_base64.c
  tool.md                      peer choices and build rules
```

The existing ignore rules cover `tools/bin/`, `tools/src/`, `tools/build/`, `tools/venv/`, and Rust `tools/wrappers/target/` output. Adapter source files remain visible so their I/O behavior can be reviewed.

Each Rust adapter has one `Cargo.toml` and one Cargo-generated `Cargo.lock` because Cargo needs package metadata and locked dependency versions. The lock files' registry checksums belong to Cargo dependency resolution; they are not fixture, binary, or benchmark fingerprints. The data directory has no manifest or per-file digest list.

## Local checks

```text
python3 tools/peer_check.py
python3 tools/peer_check.py --bench
python3 tools/peer_check.py --bench --reference tools/bin/aklomp-base64
```

The first command checks the 14 valid fixture pairs. `--bench` also checks the 25 benchmark inputs. Without `--reference`, benchmark expected bytes come from the current B64Z executable, so a repeated check does not start Aklomp. The last command runs one external Aklomp byte check for every benchmark input.

The peer commands write directly to redirected stdout. `peer_check.py` invokes each process with an argument list and compares files with a byte comparison; it does not use shell pipelines, hashes, or an intermediate text conversion. Its one-iteration B64Z `--raw` command also skips the report probe.

The current invalid fixture run found these accepted cases: Aklomp accepted `missing-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `single-character`; simdutf accepted `missing-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `whitespace`; Coreutils accepted `missing-padding` and `whitespace`; Turbo-Base64 accepted `internal-padding`, `invalid-character`, `misplaced-padding`, `nonzero-tail-one`, `nonzero-tail-two`, and `url-safe-alphabet`; Rust `base64`, Rust `base64-simd`, and Zig `std.base64` rejected all 10 invalid fixtures. These results describe the current executables and do not change the valid-byte checks.

## Build and qualification rules

1. Record the upstream version or commit before compiling.
2. Build ReleaseFast or the upstream release configuration. Do not time Debug binaries.
3. Use direct file arguments. Do not run `cat`, `dd`, shell substitutions, compression, decompression, or a second process in the timed command.
4. Write raw output directly to stdout. The peer runner redirects stdout to its comparison file.
5. Keep diagnostics on stderr and keep normal stdout byte-clean.
6. Qualify encode and decode bytes against `data/fixture/valid/*.b64` and `data/fixture/valid/*.bin` before measuring speed.
7. Run the same benchmark input through every peer. Record the mode, input path, build mode, compiler, CPU target, source version, and accepted-input differences.
8. Do not compare a peer's malformed-input behavior as a speed row unless its accepted grammar is the same as B64Z's grammar.
9. Strip retained copies in `tools/bin/` after building; build trees remain available under ignored `tools/build/` and `tools/src/` paths.

This pass builds and byte-qualifies the peer executables. It does not claim a speed ranking. Timing belongs in the benchmark runner after the command, CPU target, source revision, and output comparison have been recorded.

`tools/base64_data.py` verifies B64Z and Aklomp and maintains the small local benchmark cache. The cache uses file size, modification time, encoded length, and a direct B64Z round trip. It does not store a digest or output fingerprint. `tools/peer_check.py` qualifies every peer without moving external tools into the Zig test executable.

## Excluded from the default peer set

- [lemire/fastbase64](https://github.com/lemire/fastbase64) is archived and its README directs users to simdutf.
- [WojciechMula/base64simd](https://github.com/WojciechMula/base64simd) documents that its encoder and decoder do not process standard Base64 tails or `=` padding, so it cannot qualify against the valid fixture corpus without a separate full-group throughput row.
- OpenSSL, Python, Node.js, and language runtime commands add a different process or library boundary than the selected file utilities. Add them only as explicitly labelled application baselines.

## Current host

The first build is for `x86_64` Linux on an AMD Ryzen 9 3950X. The host has AVX2 but not AVX-512. The local toolchain reports GCC 16.2.1, Clang 22.1.8, Rust 1.98.0, Cargo 1.98.0, Zig 0.16.0, CMake 4.3.0, and GNU Make 4.4.1. These values belong in each retained benchmark record because a peer binary built for this host must not be compared with a binary built under another target or compiler setting.
