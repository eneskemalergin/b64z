# Benchmark tools

Peer selection, build settings, and file adapters used by the [benchmark reports](Benchmarking).

Encoding commands receive the same binary input and write padded Base64 to stdout. Decoding commands receive the same Base64 input and write decoded bytes. Compare speed only after those bytes match the expected output. A peer may accept malformed input that B64Z rejects; the timing comparisons use valid inputs.

## Selected peers

[Peer configuration](https://github.com/eneskemalergin/b64z/blob/main/tools/peer_config.py) records executable names, command arguments, mode coverage, and the version strings printed in reports. The notes below describe those builds, not a claim that they remain the latest upstream releases.

Run these commands from the repository root on Linux x86-64. They need Git, GCC and G++, GNU Make, CMake, Cargo, Zig 0.16.0, curl, tar, and the development headers needed by Coreutils. Use fresh source directories for the clone and extraction commands. Nothing is installed system-wide.

```sh
mkdir -p tools/bin tools/src tools/build
```

### Aklomp Base64

- Source: [aklomp/base64](https://github.com/aklomp/base64)
- Language: C99
- Selection: SIMD stream codec with runtime x86 selection and a standalone `base64` utility.
- Version: commit `bf058e571ac5002b75b03fed38e33ed4e8d45eff`.
- Build: `AVX2_CFLAGS=-mavx2 make`; the executable uses upstream runtime CPU selection.
- Encode command: `--wrap=0 INPUT`.
- Decode command: `--decode --no-strip-newlines INPUT`.
- Difference: its decoder accepts some noncanonical inputs that B64Z rejects.

Aklomp is the external byte reference for canonical valid inputs.

```sh
git clone https://github.com/aklomp/base64 tools/src/aklomp-base64
git -C tools/src/aklomp-base64 checkout --detach bf058e571ac5002b75b03fed38e33ed4e8d45eff
make -C tools/src/aklomp-base64 -j2 AVX2_CFLAGS=-mavx2
install -s tools/src/aklomp-base64/bin/base64 tools/bin/aklomp-base64
```

### simdutf `fastbase64`

- Source: [simdutf/simdutf](https://github.com/simdutf/simdutf)
- Language: C++17.
- Version: `v9.2.0`, commit `8abc1d7a466bc882c2d72e1effd8661492db257c`.
- Selection: a C++ SIMD Base64 library with runtime CPU dispatch.
- Build: Release CMake build with the upstream CPU dispatch, followed by a small C++ adapter linked to the simdutf Base64 library.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Adapter source: `tools/wrappers/simdutf_base64.cpp`.
- Adapter reason: the upstream utility appends a newline after encoded output. The retained binary calls the same simdutf library directly so stdout contains only Base64 bytes and the file boundary does not add a formatting write.
- Difference: its decoder is WHATWG-forgiving and is checked only against valid canonical inputs in the peer runner.

```sh
git clone --depth 1 --branch v9.2.0 https://github.com/simdutf/simdutf tools/src/simdutf
git -C tools/src/simdutf checkout --detach 8abc1d7a466bc882c2d72e1effd8661492db257c
cmake -S tools/src/simdutf -B tools/build/simdutf -DCMAKE_BUILD_TYPE=Release -DSIMDUTF_TESTS=OFF -DSIMDUTF_BENCHMARKS=OFF -DSIMDUTF_TOOLS=ON
cmake --build tools/build/simdutf --target simdutf-base64 --parallel 2
g++ -O3 -DNDEBUG -std=c++17 -Itools/src/simdutf/include tools/wrappers/simdutf_base64.cpp tools/build/simdutf/src/libsimdutf-base64.a -o tools/bin/simdutf-fastbase64
strip tools/bin/simdutf-fastbase64
```

### GNU Coreutils `base64`

- Source: [GNU Coreutils](https://www.gnu.org/software/coreutils/)
- Language: C.
- Version: `9.11`, from the [GNU release directory](https://ftp.gnu.org/gnu/coreutils/).
- Selection: a widely used command-line converter with file arguments.
- Build: release source tarball with `configure` and `make`; the retained reports record `-g -O2`.
- Encode command: `-w 0 INPUT`.
- Decode command: `--decode INPUT`.
- Difference: GNU decoding is more permissive than B64Z decoding.
- License: GPLv3.

```sh
curl -fL https://ftp.gnu.org/gnu/coreutils/coreutils-9.11.tar.xz -o tools/src/coreutils-9.11.tar.xz
tar -xf tools/src/coreutils-9.11.tar.xz -C tools/src
(
    cd tools/src/coreutils-9.11
    CFLAGS='-g -O2' ./configure --disable-nls
    make -j2
)
install -s tools/src/coreutils-9.11/src/base64 tools/bin/coreutils-base64
```

### Turbo-Base64

- Source: [powturbo/Turbo-Base64](https://github.com/powturbo/Turbo-Base64)
- Language: C with C++ headers.
- Version: commit `d9e584363280055ba6355938a48dc3711183f50f`.
- Selection: a C library with whole-buffer `tb64enc` and `tb64dec` calls.
- Build: the upstream `make -f makefile` target plus a small file adapter around `tb64enc` and `tb64dec`.
- Adapter source: `tools/wrappers/turbo_base64.c`.
- Encode command: `INPUT`.
- Decode command: `--decode INPUT`.
- Difference: the upstream API reports `0` for an empty decode and has its own error rules. Use it for valid-byte throughput after qualification, not as the strict invalid-input reference.
- License: GPLv3 with a commercial license path.

```sh
git clone https://github.com/powturbo/Turbo-Base64 tools/src/turbo-base64
git -C tools/src/turbo-base64 checkout --detach d9e584363280055ba6355938a48dc3711183f50f
make -C tools/src/turbo-base64 -f makefile -j2 libtb64.a
gcc -O3 -DNDEBUG -Itools/src/turbo-base64 tools/wrappers/turbo_base64.c tools/src/turbo-base64/libtb64.a -o tools/bin/turbo-base64
strip tools/bin/turbo-base64
```

### Rust `base64`

- Source: [marshallpierce/rust-base64](https://github.com/marshallpierce/rust-base64)
- Language: Rust.
- Version: `0.23.1`, fixed by the adapter's `Cargo.lock`.
- Selection: the `Simd` engine, which selects AVX2 on x86-64 and NEON on AArch64 at runtime before falling back to the scalar engine.
- Build: Cargo `--release` with fat LTO, one codegen unit, and the crate's default runtime SIMD detection.
- Adapter: a direct file-to-stdout wrapper that allocates an initialized output vector and uses the crate slice APIs for memory mode.

```sh
cargo build --release --locked --manifest-path tools/wrappers/rust_base64/Cargo.toml --target-dir tools/build/rust_base64
install -s tools/build/rust_base64/release/rust-base64-peer tools/bin/rust-base64-simd
```

### Rust `base64-simd`

- Source: [Nugine/simd](https://github.com/Nugine/simd)
- Language: Rust.
- Version: `0.8.0`, fixed by the adapter's `Cargo.lock`.
- Selection: SIMD Base64 crate with default runtime feature detection.
- Build: Cargo `--release` with fat LTO, one codegen unit, and default `detect`, `std`, and `alloc` features.
- Adapter: a direct file-to-stdout wrapper using preallocated `encode` and `decode` output slices.

The two Rust rows measure different crates and allocation APIs.

```sh
cargo build --release --locked --manifest-path tools/wrappers/rust_base64_simd/Cargo.toml --target-dir tools/build/rust_base64_simd
install -s tools/build/rust_base64_simd/release/rust-base64-simd-peer tools/bin/rust-base64-simd-crate
```

### Zig `std.base64`

- Source: the Zig standard library installed for this repository.
- Language: Zig.
- Version: `0.16.0`.
- Selection: standard-library reference peer, not a second copy of B64Z.
- Build: `zig build-exe -O ReleaseFast -mcpu=native` for the local adapter.
- Adapter: a direct file-to-stdout wrapper around `std.base64.standard`.
- Decode comparisons use valid canonical inputs; this adapter is not the reference for B64Z error classes.

```sh
zig build-exe tools/wrappers/zig_std_base64.zig -O ReleaseFast -mcpu=native -femit-bin=tools/bin/zig-std-base64
```

The retained Zig peer is ReleaseFast but keeps debug information. The other peer executables are stripped. The command above preserves that recorded build choice.

## Mode selection and adapters

Aklomp and GNU Coreutils use their upstream streaming commands for encoding and decoding. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 use whole-input adapters with separate input and output buffers. The [adapter sources](https://github.com/eneskemalergin/b64z/tree/main/tools/wrappers) show their file reads, allocation, codec calls, and output writes.

Aklomp and GNU Coreutils may expose whole-buffer library functions, but the selected commands stream, so they do not appear in memory rows. Whole-input adapters do not appear in streaming rows. These choices describe the commands being measured, not every use of each library.

## Check bytes before timing

Build the selected peer executables with the settings above and the executable names recorded in the peer configuration. The benchmark scripts expect those executables to exist; they do not download or build them.

```sh
python3 tools/base64_data.py generate
bash bench/linux-x86-avx2/run.sh --skip-benchmarks --skip-report
bash bench/linux-x86-scalar/run.sh --skip-benchmarks --skip-report
```

The generator creates valid and invalid fixtures and benchmark inputs. Each target command builds B64Z, then checks all B64Z modes, invalid-input errors, Aklomp, and every selected peer against the benchmark inputs without running timings.

The verifier compares output files byte for byte before timing. When changing a peer build or adapter, record its version and build flags, use its release configuration, and rerun these checks. Each timed command must read `INPUT` directly, write only converted bytes to stdout, and send diagnostics to stderr. Keep shell pipelines and compression outside the timed command.

Use the same valid input cases for every selected peer. Their malformed-input rules differ, so invalid-input checks apply only to B64Z. [Benchmarking](Benchmarking#run) describes the timing commands and report files.

## Excluded from the default peer set

- [lemire/fastbase64](https://github.com/lemire/fastbase64) is archived and its README directs users to simdutf.
- [WojciechMula/base64simd](https://github.com/WojciechMula/base64simd) documents that its encoder and decoder do not process standard Base64 tails or `=` padding, so it cannot qualify against the valid fixture corpus without a separate full-group throughput row.
