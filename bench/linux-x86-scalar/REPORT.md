# B64Z benchmark: linux-x86-scalar

Generated: `2026-09-19T21:49:06Z`

B64Z: `custom-base64 0.1.0 backend=scalar optimize=ReleaseFast target=x86_64`

## Result

B64Z is the 1.0x reference in each mode. Time and RSS ratios use the geometric mean of 25 input cases. Values above 1.0x mean that the tool took more time or used more RSS than B64Z.

The memory and streaming rows stay separate. A peer appears only in the mode that its selected executable actually runs.

| Mode | Tool | Time / B64Z | RSS / B64Z | Faster than B64Z | Lower RSS than B64Z | Huge time (ms) | Huge RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `encode-memory` | B64Z | 1.000x | 1.000x | - | - | 66.995 | 74.74 |
| `encode-memory` | simdutf | 1.351x | 2.315x | 9 | 0 | 53.197 | 78.10 |
| `encode-memory` | Turbo-Base64 | 0.911x | 1.304x | 16 | 0 | 51.486 | 75.89 |
| `encode-memory` | Rust base64 | 1.115x | 1.578x | 10 | 0 | 59.640 | 76.47 |
| `encode-memory` | Rust base64-simd | 1.109x | 1.575x | 11 | 0 | 58.530 | 76.51 |
| `encode-memory` | Zig std.base64 | 0.965x | 0.999x | 23 | 3 | 62.992 | 74.72 |
| `encode-streaming` | B64Z | 1.000x | 1.000x | - | - | 22.871 | 0.92 |
| `encode-streaming` | Aklomp | 1.035x | 2.435x | 9 | 0 | 13.237 | 3.69 |
| `encode-streaming` | GNU coreutils | 1.235x | 1.788x | 0 | 0 | 23.496 | 1.82 |
| `decode-memory` | B64Z | 1.000x | 1.000x | - | - | 70.379 | 74.72 |
| `decode-memory` | simdutf | 1.320x | 2.306x | 10 | 0 | 54.372 | 78.17 |
| `decode-memory` | Turbo-Base64 | 0.888x | 1.288x | 15 | 0 | 53.363 | 75.85 |
| `decode-memory` | Rust base64 | 1.044x | 1.562x | 13 | 0 | 55.743 | 76.48 |
| `decode-memory` | Rust base64-simd | 1.071x | 1.555x | 13 | 0 | 58.737 | 76.46 |
| `decode-memory` | Zig std.base64 | 0.933x | 0.998x | 25 | 7 | 63.140 | 74.66 |
| `decode-streaming` | B64Z | 1.000x | 1.000x | - | - | 28.194 | 0.91 |
| `decode-streaming` | Aklomp | 1.047x | 2.463x | 9 | 0 | 19.719 | 3.11 |
| `decode-streaming` | GNU coreutils | 1.865x | 1.884x | 0 | 0 | 68.585 | 1.66 |

`Faster than B64Z` and `Lower RSS than B64Z` count cases where the peer is strictly below the B64Z value. They are not a combined score.

## Figures

The throughput figure averages the five data forms at each size: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib. The isocost figure summarizes all 25 cases and shows the middle 50% of per-case ratios as bars.

![Throughput by input size](figures/scaling.svg)

![Speed and memory ratios](figures/isocost.svg)

PNG copies are in [`figures/`](figures/) for local use.

## What was measured

Each command reads one file and writes Base64 or decoded bytes to stdout. Zebrac discards child stdout, so output comparison is separate from the timed command. Process startup, file reads, allocation, encoding or decoding, and stdout writes are included in the measured process.

Zebrac ran `20` measured samples after `5` warmups, with a `15000 ms` duration ceiling and an exact maximum sample count. Every recorded command has zero failed samples.

B64Z uses chunk `65536` for both memory command lines and chunks `8191` and `4093` for the two streaming command lines. The memory command passes the chunk flag for a stable command record; its whole-file path does not use the streaming buffer.

Correctness checks passed for B64Z and every selected peer. The run checks valid fixtures, invalid B64Z error cases, and all 25 benchmark inputs before timing.

The byte checks compare B64Z and every selected peer against the canonical padded bytes produced by Aklomp.

The largest B64Z A/A mean-time gap on the huge general input was `0.63%` across the four modes.

## Data

The benchmark contains 25 byte inputs: 5 general inputs, 10 float32 mzML payload inputs, and 10 float64 mzML payload inputs. Each family has tiny, small, medium, large, and huge sizes at 256 B, 16 KiB, 1 MiB, 8 MiB, and 32 MiB. The zlib files are compressed payload bytes, not XML documents.

Decode rows read generated canonical Base64 files under `bench/work/inputs/encoded/`. Their size and modification time are checked before reuse. No digest list or per-input manifest is used.

## Tools and versions

| Tool | Selected modes | Version or build | Executable |
| --- | --- | --- | --- |
| B64Z | all four | `custom-base64 0.1.0 backend=scalar optimize=ReleaseFast target=x86_64`; `zig -Dcpu=x86_64 -Doptimize=ReleaseFast -Dstrip=true` | `bench/linux-x86-scalar/bin/custom-base64` |
| Aklomp | encode-streaming, decode-streaming | `aklomp/base64 bf058e571ac5002b75b03fed38e33ed4e8d45eff, upstream make` | `tools/bin/aklomp-base64` |
| simdutf | encode-memory, decode-memory | `simdutf v9.2.0 8abc1d7a466bc882c2d72e1effd8661492db257c, Release CMake and direct C++ adapter` | `tools/bin/simdutf-fastbase64` |
| GNU coreutils | encode-streaming, decode-streaming | `GNU coreutils base64 9.11, local build flags -g -O2` | `tools/bin/coreutils-base64` |
| Turbo-Base64 | encode-memory, decode-memory | `Turbo-Base64 d9e584363280055ba6355938a48dc3711183f50f, upstream make and direct C adapter` | `tools/bin/turbo-base64` |
| Rust base64 | encode-memory, decode-memory | `Rust base64 crate 0.23.1, Simd engine, Cargo release fat LTO` | `tools/bin/rust-base64-simd` |
| Rust base64-simd | encode-memory, decode-memory | `Rust base64-simd crate 0.8.0, Cargo release fat LTO` | `tools/bin/rust-base64-simd-crate` |
| Zig std.base64 | encode-memory, decode-memory | `Zig 0.16.0 std.base64, ReleaseFast -Dcpu=native adapter` | `tools/bin/zig-std-base64` |

The Aklomp and GNU Coreutils command rows are streaming rows because those selected executables expose file-processing commands, not the memory adapters used by the other peers. The Rust, simdutf, Turbo-Base64, and Zig rows use the local direct file adapters listed in `tools/tool.md`.

## Reading the result

- `encode-memory`: B64Z has lower geometric-mean time than Turbo-Base64, Zig std.base64; higher than simdutf, Rust base64, Rust base64-simd. Lower geometric-mean RSS: Zig std.base64.
- `encode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.
- `decode-memory`: B64Z has lower geometric-mean time than Turbo-Base64, Zig std.base64; higher than simdutf, Rust base64, Rust base64-simd. Lower geometric-mean RSS: Zig std.base64.
- `decode-streaming`: B64Z has the lowest geometric-mean time among the listed rows. No listed peer has lower geometric-mean RSS.

## Run conditions

- Host: `AMD Ryzen 9 3950X 16-Core Processor`, `x86_64`, `32 logical CPUs`.
- Kernel: `7.2.5-200.fc44.x86_64`; CPU governor: `schedutil`.
- Git commit: `4c20443`; tracked changes at measurement time: `yes`.
- Runner: `zebrac 0.6.2`; gnuplot: `gnuplot 6.0.3 patchlevel 3`; Zig: `0.16.0`.
- The file cache is warm after verification. The runner does not pin processes to a CPU or flush the page cache.
- These numbers describe the named local binaries on this host. They do not describe a peer library without its command adapter or a different compiler build.

## Files

- [`measurements.tsv`](measurements.tsv) contains one row for every measured command and input, including sample quartiles and the exact command string.
- [`summary.tsv`](summary.tsv) contains the values used by the tables and figures.
- `bench/work/` contains ignored encoded inputs and raw Zebrac JSON for rerendering during local work.

The report does not produce one report per input. The table and the two figures cover the complete 100 groups without turning each input into a separate publication page.
