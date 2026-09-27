# B64Z benchmark: linux-x86-avx2

Generated: `2026-09-23T18:55:49Z`

B64Z: `custom-base64 0.1.0 backend=avx2 optimize=ReleaseFast target=x86_64`

## Terms

For B64Z, `memory` means the command reads the complete input into one buffer and converts it in place. `Streaming` means the command uses fixed input and output buffers. The [benchmark method](../../wiki/Benchmarking.md) describes the inputs and measurements.

`Peak RSS` is the per-sample maximum resident set size reported by Zebrac for the timed process. The table and ratios use the mean of those per-sample peaks. It includes the executable, runtime, file I/O buffers, codec state, and resident input or output allocations; it is not the size of one buffer. `RSS / B64Z` compares that process value with B64Z in the same mode and input case.

The nominal size names are `tiny` = 256 B, `small` = 16 KiB, `medium` = 1 MiB, `large` = 8 MiB, and `huge` = 32 MiB. For zlib cases, these name the array before compression; the binary file passed to the encoder is smaller. Decode modes read padded Base64 of the corresponding binary file.

## Result

> [!NOTE]
> **Peer settings and memory allocation**
>
> Peers retain the build and CPU dispatch settings described in [Benchmark tools](../../wiki/Benchmark-Tools.md), including AVX2 for the tools built to use it. The scalar target changes B64Z only.
>
> B64Z's memory modes convert in place and request Linux transparent huge pages for large buffers. Our peer memory adapters use separate input and output buffers; we did not add huge-page advice to them. The reported command time and peak RSS include these allocation differences, along with startup, file I/O, and codec work.

B64Z is the 1.0x reference in each mode. Time and RSS ratios use the geometric mean of 25 input cases. Values above 1.0x mean that the tool took more time or used more RSS than B64Z.

The full-input memory and streaming rows stay separate. A peer appears only in the mode that its selected executable actually runs.

| Mode               | Tool             | Time / B64Z | RSS / B64Z | Faster than B64Z | Lower RSS than B64Z | Huge time (ms) | Huge RSS (MiB) |
| ------------------ | ---------------- | ----------: | ---------: | ---------------: | ------------------: | -------------: | -------------: |
| `encode-memory`    | B64Z             |      1.000x |     1.000x |                - |                   - |         12.584 |          42.71 |
| `encode-memory`    | simdutf          |      3.435x |     3.252x |                0 |                   0 |         53.614 |          78.07 |
| `encode-memory`    | Turbo-Base64     |      2.290x |     1.835x |                0 |                   0 |         52.398 |          75.91 |
| `encode-memory`    | Rust base64      |      2.823x |     2.221x |                0 |                   0 |         60.592 |          76.44 |
| `encode-memory`    | Rust base64-simd |      2.816x |     2.214x |                0 |                   0 |         60.239 |          76.42 |
| `encode-memory`    | Zig std.base64   |      2.450x |     1.439x |                0 |                   1 |         63.829 |          74.90 |
| `encode-streaming` | B64Z             |      1.000x |     1.000x |                - |                   - |          5.361 |           0.92 |
| `encode-streaming` | Aklomp           |      2.017x |     2.462x |                0 |                   0 |          7.491 |           3.71 |
| `encode-streaming` | GNU coreutils    |      2.836x |     1.772x |                0 |                   0 |         23.456 |           1.79 |
| `decode-memory`    | B64Z             |      1.000x |     1.000x |                - |                   - |         16.047 |          42.58 |
| `decode-memory`    | simdutf          |      3.268x |     3.000x |                0 |                   0 |         59.139 |          78.03 |
| `decode-memory`    | Turbo-Base64     |      2.191x |     1.675x |                0 |                   0 |         56.783 |          75.84 |
| `decode-memory`    | Rust base64      |      2.541x |     2.025x |                0 |                   0 |         59.933 |          76.40 |
| `decode-memory`    | Rust base64-simd |      2.621x |     2.019x |                0 |                   0 |         63.451 |          76.38 |
| `decode-memory`    | Zig std.base64   |      2.309x |     1.424x |                0 |                  11 |         67.521 |          74.92 |
| `decode-streaming` | B64Z             |      1.000x |     1.000x |                - |                   - |          8.345 |           1.05 |
| `decode-streaming` | Aklomp           |      1.804x |     2.366x |                0 |                   0 |         10.345 |           3.11 |
| `decode-streaming` | GNU coreutils    |      4.160x |     1.818x |                0 |                   0 |         70.029 |           1.67 |

`Faster than B64Z` and `Lower RSS than B64Z` count cases where the peer is strictly below the B64Z value. They are not a combined score.

## Figures

The figures use the inputs and method described in [Benchmarking](../../wiki/Benchmarking.md).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/scaling-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="figures/scaling-light.svg">
    <img src="figures/scaling-light.svg" alt="Throughput by input size" width="100%">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/isocost-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="figures/isocost-light.svg">
    <img src="figures/isocost-light.svg" alt="Speed and peak RSS ratios with combined-cost curves" width="100%">
  </picture>
</p>

## Measurement

Zebrac ran `20` measured samples after `5` warmups, with a `15000 ms` duration ceiling and an exact maximum sample count. Every recorded command has zero failed samples.

B64Z passes chunks `8191` and `4093` to the streaming command lines. Memory command lines do not pass `--chunk`.

Correctness checks passed for B64Z and every selected peer. The run checks valid fixtures, invalid B64Z error cases, and all 25 benchmark inputs before timing.

The byte checks compare B64Z and every selected peer against Aklomp's canonical padded bytes.

The largest B64Z A/A mean-time gap on the huge general input was `2.10%` across the four modes.

## Data

The case sizes, byte forms, and compression details are listed in [Benchmarking](../../wiki/Benchmarking.md#input-sizes).

## Tools and versions

- **B64Z** (all four modes): `custom-base64 0.1.0 backend=avx2 optimize=ReleaseFast target=x86_64`; `zig build -Dcpu=haswell -Doptimize=ReleaseFast -Dstrip=true`.
- **Aklomp** (encode-streaming, decode-streaming): `aklomp/base64 bf058e571ac5002b75b03fed38e33ed4e8d45eff, AVX2_CFLAGS=-mavx2 upstream make`.
- **simdutf** (encode-memory, decode-memory): `simdutf v9.2.0 8abc1d7a466bc882c2d72e1effd8661492db257c, Release CMake and direct C++ adapter`.
- **GNU coreutils** (encode-streaming, decode-streaming): `GNU coreutils base64 9.11, local build flags -g -O2`.
- **Turbo-Base64** (encode-memory, decode-memory): `Turbo-Base64 d9e584363280055ba6355938a48dc3711183f50f, upstream make and direct C adapter`.
- **Rust base64** (encode-memory, decode-memory): `Rust base64 crate 0.23.1, Simd engine, Cargo release fat LTO`.
- **Rust base64-simd** (encode-memory, decode-memory): `Rust base64-simd crate 0.8.0, Cargo release fat LTO`.
- **Zig std.base64** (encode-memory, decode-memory): `Zig 0.16.0 std.base64, ReleaseFast -Dcpu=native adapter`.

Peer commands and their mode coverage are described in [Benchmark tools](../../wiki/Benchmark-Tools.md).

## Reading the result

- `encode-memory`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.
- `encode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.
- `decode-memory`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.
- `decode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.

## Run conditions

- Host: `AMD Ryzen 9 3950X 16-Core Processor`, `x86_64`, `32 logical CPUs`.
- Kernel: `7.2.5-200.fc44.x86_64`; CPU governor: `schedutil`.
- Git commit: `3309e5b8a7b27b359bc3fed8f6524ea0a7d6a79b`; project changes at measurement time: `no`.
- Runner: `zebrac 0.6.2`; gnuplot: `gnuplot 6.0.3 patchlevel 3`; Zig: `0.16.0`.
- Host tools: GCC `gcc (GCC) 16.2.1 20260819 (Red Hat 16.2.1-2)`; Clang `clang version 22.1.8 (Fedora 22.1.8-4.fc44)`; Rust `rustc 1.98.0 (88d9e12ae 2026-08-18)`; Cargo `cargo 1.98.0 (797e8a9bc 2026-08-05)`; CMake `cmake version 4.3.0`; Make `GNU Make 4.4.1`.
- The file cache is warm after verification. The runner does not pin processes to a CPU or flush the page cache.
- The target changes the B64Z build. Peer binaries keep their native build and runtime dispatch settings.

## Files

[`measurements.tsv`](measurements.tsv) contains the measured rows. [`summary.tsv`](summary.tsv) contains the values used by the table and figures.
