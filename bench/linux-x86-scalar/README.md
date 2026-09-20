# B64Z benchmark: linux-x86-scalar

Generated: `2026-09-19T22:39:36Z`

B64Z: `custom-base64 0.1.0 backend=scalar optimize=ReleaseFast target=x86_64`

## Terms

In a mode name, `memory` describes complete-input processing, not the memory metric. B64Z reads the complete input into an allocated buffer and allocates a complete output buffer. `Streaming` describes incremental processing through fixed input and output buffers.

`Peak RSS` is the per-sample maximum resident set size reported by Zebrac for the timed process. The table and ratios use the mean of those per-sample peaks. It includes the executable, runtime, file I/O buffers, codec state, and resident input or output allocations; it is not the size of one buffer. `RSS / B64Z` compares that process value with B64Z in the same mode and input case.

The size names refer to the raw case bytes: `tiny` = 256 B, `small` = 16 KiB, `medium` = 1 MiB, `large` = 8 MiB, and `huge` = 32 MiB. Decode modes read the corresponding padded Base64 file, which is larger than the raw case.

## Result

B64Z is the 1.0x reference in each mode. Time and RSS ratios use the geometric mean of 25 input cases. Values above 1.0x mean that the tool took more time or used more RSS than B64Z.

The full-input memory and streaming rows stay separate. A peer appears only in the mode that its selected executable actually runs.

| Mode               | Tool             | Time / B64Z | RSS / B64Z | Faster than B64Z | Lower RSS than B64Z | Huge time (ms) | Huge RSS (MiB) |
| ------------------ | ---------------- | ----------: | ---------: | ---------------: | ------------------: | -------------: | -------------: |
| `encode-memory`    | B64Z             |      1.000x |     1.000x |                - |                   - |         64.429 |          74.71 |
| `encode-memory`    | simdutf          |      1.356x |     2.310x |                9 |                   0 |         51.899 |          78.09 |
| `encode-memory`    | Turbo-Base64     |      0.906x |     1.308x |               15 |                   0 |         50.279 |          75.89 |
| `encode-memory`    | Rust base64      |      1.108x |     1.575x |               11 |                   0 |         57.824 |          76.48 |
| `encode-memory`    | Rust base64-simd |      1.104x |     1.578x |               12 |                   0 |         57.124 |          76.51 |
| `encode-memory`    | Zig std.base64   |      0.970x |     0.998x |               21 |                  10 |         61.690 |          74.71 |
| `encode-streaming` | B64Z             |      1.000x |     1.000x |                - |                   - |         22.842 |           0.92 |
| `encode-streaming` | Aklomp           |      1.032x |     2.431x |                9 |                   0 |         13.216 |           3.71 |
| `encode-streaming` | GNU coreutils    |      1.243x |     1.778x |                0 |                   0 |         23.692 |           1.81 |
| `decode-memory`    | B64Z             |      1.000x |     1.000x |                - |                   - |         69.633 |          74.74 |
| `decode-memory`    | simdutf          |      1.326x |     2.301x |               10 |                   0 |         53.407 |          78.15 |
| `decode-memory`    | Turbo-Base64     |      0.890x |     1.291x |               15 |                   0 |         52.579 |          75.88 |
| `decode-memory`    | Rust base64      |      1.037x |     1.561x |               14 |                   0 |         53.981 |          76.49 |
| `decode-memory`    | Rust base64-simd |      1.069x |     1.560x |               12 |                   0 |         57.266 |          76.54 |
| `decode-memory`    | Zig std.base64   |      0.938x |     1.000x |               21 |                   3 |         61.972 |          74.74 |
| `decode-streaming` | B64Z             |      1.000x |     1.000x |                - |                   - |         29.985 |           0.91 |
| `decode-streaming` | Aklomp           |      1.017x |     2.424x |                9 |                   0 |         19.278 |           3.10 |
| `decode-streaming` | GNU coreutils    |      1.820x |     1.863x |                0 |                   0 |         68.266 |           1.71 |

`Faster than B64Z` and `Lower RSS than B64Z` count cases where the peer is strictly below the B64Z value. They are not a combined score.

## Figures

The throughput figure averages the five data forms at each size: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib. The isocost figure shows one small dot for each of the 25 cases, larger markers for geometric means, middle-50% error bars, and dotted curves for the combined cost C = (wall time / B64Z) * (peak RSS / B64Z). Lower curves are better.

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

## What was measured

Each row starts one named command for one input. The command reads a file and writes Base64 or decoded bytes to standard output. Zebrac discards child output during timing, so byte comparison runs before measurement. Process startup, file reads, allocation, encoding or decoding, and standard-output writes are included in the measured process.

Zebrac ran `20` measured samples after `5` warmups, with a `15000 ms` duration ceiling and an exact maximum sample count. Every recorded command has zero failed samples.

B64Z uses chunk `65536` for both memory command lines and chunks `8191` and `4093` for the two streaming command lines. The memory command passes the chunk flag for a stable command record; its whole-file path does not use the streaming buffer.

Correctness checks passed for B64Z and every selected peer. The run checks valid fixtures, invalid B64Z error cases, and all 25 benchmark inputs before timing.

The byte checks compare B64Z and every selected peer against the canonical padded bytes produced by Aklomp.

The largest B64Z A/A mean-time gap on the huge general input was `0.97%` across the four modes.

## Data

The benchmark contains 25 byte inputs: 5 general inputs, 10 float32 mzML payload inputs, and 10 float64 mzML payload inputs. Each size has five forms: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib. `tiny` is 256 B, `small` is 16 KiB, `medium` is 1 MiB, `large` is 8 MiB, and `huge` is 32 MiB. The zlib files are compressed payload bytes, not XML documents.

## Tools and versions

- **B64Z** (all four modes): `custom-base64 0.1.0 backend=scalar optimize=ReleaseFast target=x86_64`; `zig -Dcpu=x86_64 -Doptimize=ReleaseFast -Dstrip=true`.
- **Aklomp** (encode-streaming, decode-streaming): `aklomp/base64 bf058e571ac5002b75b03fed38e33ed4e8d45eff, upstream make`.
- **simdutf** (encode-memory, decode-memory): `simdutf v9.2.0 8abc1d7a466bc882c2d72e1effd8661492db257c, Release CMake and direct C++ adapter`.
- **GNU coreutils** (encode-streaming, decode-streaming): `GNU coreutils base64 9.11, local build flags -g -O2`.
- **Turbo-Base64** (encode-memory, decode-memory): `Turbo-Base64 d9e584363280055ba6355938a48dc3711183f50f, upstream make and direct C adapter`.
- **Rust base64** (encode-memory, decode-memory): `Rust base64 crate 0.23.1, Simd engine, Cargo release fat LTO`.
- **Rust base64-simd** (encode-memory, decode-memory): `Rust base64-simd crate 0.8.0, Cargo release fat LTO`.
- **Zig std.base64** (encode-memory, decode-memory): `Zig 0.16.0 std.base64, ReleaseFast -Dcpu=native adapter`.

Aklomp and GNU Coreutils appear only in streaming rows because their selected commands process files incrementally. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 appear only in memory rows because their selected adapters allocate complete input and output buffers.

## Reading the result

- `encode-memory`: B64Z has lower geometric-mean time than Turbo-Base64, Zig std.base64; higher than simdutf, Rust base64, Rust base64-simd. Lower geometric-mean RSS: Zig std.base64.
- `encode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.
- `decode-memory`: B64Z has lower geometric-mean time than Turbo-Base64, Zig std.base64; higher than simdutf, Rust base64, Rust base64-simd. Lower geometric-mean RSS: Zig std.base64.
- `decode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.

## Run conditions

- Host: `AMD Ryzen 9 3950X 16-Core Processor`, `x86_64`, `32 logical CPUs`.
- Kernel: `7.2.5-200.fc44.x86_64`; CPU governor: `schedutil`.
- Git commit: `b211e3b67bd1e50fa574aa26323e50468082fe50`; worktree changes at measurement time: `yes`.
- Runner: `zebrac 0.6.2`; gnuplot: `gnuplot 6.0.3 patchlevel 3`; Zig: `0.16.0`.
- Host tools: GCC `gcc (GCC) 16.2.1 20260819 (Red Hat 16.2.1-2)`; Clang `clang version 22.1.8 (Fedora 22.1.8-4.fc44)`; Rust `rustc 1.98.0 (88d9e12ae 2026-08-18)`; Cargo `cargo 1.98.0 (797e8a9bc 2026-08-05)`; CMake `cmake version 4.3.0`; Make `GNU Make 4.4.1`.
- The file cache is warm after verification. The runner does not pin processes to a CPU or flush the page cache.
- These numbers describe the named commands, adapters, and builds on this host. They do not describe a peer library without its command adapter or a different compiler build.
- The target choice changes the B64Z build only. Peer binaries keep their own native build and runtime dispatch settings. The scalar page is not a scalar-for-every-peer instruction-set test.

## Files

- [`measurements.tsv`](measurements.tsv) contains one row for every measured command and input, including sample quartiles and a public command label.
- [`summary.tsv`](summary.tsv) contains the values used by the tables and figures.

The report does not produce one report per input. The table and the two figures cover the complete 100 groups without turning each input into a separate publication page.
