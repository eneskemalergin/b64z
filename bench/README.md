# Benchmark reports

This directory contains two retained Linux x86-64 benchmark pages:

- [`linux-x86-avx2/`](linux-x86-avx2/) measures the `haswell` build with the B64Z AVX2 backend.
- [`linux-x86-scalar/`](linux-x86-scalar/) measures the `x86_64` build with the B64Z scalar backend.

Each target page contains its result table, light and dark SVG figures, raw measurement table, and summary table.

## Status of these results

The retained pages were measured on 2026-09-19 from commit `b211e3b` with uncommitted changes. They do not describe the current B64Z build, and they will be replaced by a new run. Since that run:

- The AVX2 encode and decode kernels changed.
- Memory modes convert in one buffer instead of separate input and output buffers, and ask Linux for transparent huge pages.
- The streaming decoder no longer scans each chunk twice, and release builds no longer reserve an unused 256 KiB signal stack.

The Aklomp executable used for these pages was built with its SIMD options disabled and contains no AVX2 instructions, so its rows measure Aklomp's scalar path. The current local executable was rebuilt with `AVX2_CFLAGS=-mavx2`; upstream runtime dispatch selects AVX2 on this host.

## Compared operations

The four B64Z modes are `encode-memory`, `decode-memory`, `encode-streaming`, and `decode-streaming`.

In a mode name, `memory` means complete-input processing, not the measured memory value. B64Z reads the complete input into one buffer and converts it in place; for encoding, that buffer also holds the encoded output. The retained pages predate this and used separate input and output buffers. The peer memory adapters keep separate input and output buffers. `Streaming` means incremental processing through fixed input and output buffers. A peer appears only in the mode selected for its command and adapter. Aklomp and GNU Coreutils appear in streaming rows. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 appear in memory rows.

`Peak RSS` is the per-sample maximum resident set size reported by Zebrac for the timed process. The reports use the mean of those per-sample peaks. It includes the executable, runtime, file I/O buffers, codec state, and resident input or output allocations. It is not the size of one codec buffer.

## Input sizes

The five size names refer to the raw case bytes: `tiny` is 256 B, `small` is 16 KiB, `medium` is 1 MiB, `large` is 8 MiB, and `huge` is 32 MiB. Decode modes read the corresponding padded Base64 file, which is larger than the raw case. Each size has five forms: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib.

## Method

Each row starts one command for one input. B64Z streaming rows pass `--chunk 8191` for encoding and `--chunk 4093` for decoding, so each 64 KiB read is converted in several `update` calls. Memory rows read the complete input into one buffer and convert it in place; they do not pass `--chunk`. Peer memory adapters use separate input and output buffers. The timed process includes startup, file reads, allocation, Base64 work, and standard-output writes. Zebrac runs 20 measured samples after 5 warmups with a 15,000 ms duration ceiling. The reports use the geometric mean of 25 cases and show the huge-input result separately.

Byte checks run before timing. B64Z and every selected peer are compared with canonical padded Base64 bytes from Aklomp. Invalid-input checks apply only to B64Z because the selected peers accept different grammars.

These pages describe named command lines and builds on one Linux x86-64 host. They do not claim library-only instruction speed, a ranking on another host, or a result for an unlisted adapter.

The target choice changes the B64Z build only. Peer binaries keep their own native build and runtime dispatch settings. The scalar page therefore compares B64Z scalar code with those peer builds; it is not a scalar-for-every-peer instruction-set test.

A measurement or report-writing run refuses a worktree with project changes. Generated benchmark pages do not count as project changes, so the AVX2 and scalar pages can be measured in separate runs from the same commit.

## Run

The retained target scripts are:

```sh
bash bench/linux-x86-avx2/run.sh
bash bench/linux-x86-scalar/run.sh
```

The scripts require the Linux x86-64 toolchain and local qualification setup described in [`tools/tool.md`](../tools/tool.md). A publication run uses the default sample policy and byte checks. `--skip-benchmarks --skip-report` builds the selected B64Z target and runs byte checks without Zebrac or gnuplot.

## Tracked files

- `README.md` records the target result and run conditions. This file owns the shared method.
- `measurements.tsv` contains one row for each measured command and case.
- `summary.tsv` contains the values used by the result table and figures.
- `figures/scaling-light.svg` and `figures/scaling-dark.svg` show throughput by nominal size.
- `figures/isocost-light.svg` and `figures/isocost-dark.svg` show one dot per input case, geometric means, peak-RSS ratios to B64Z, and combined-cost curves.
- `linux-x86-avx2/figures/summary-light.svg` and `linux-x86-avx2/figures/summary-dark.svg` show the AVX2 summary used by the main README.

The pages cover all 100 mode-and-case groups without creating one public page per input.
