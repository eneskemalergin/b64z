# Benchmark reports

This directory contains two retained Linux x86-64 benchmark pages:

- [`linux-x86-avx2/`](linux-x86-avx2/) measures the `haswell` build with the B64Z AVX2 backend.
- [`linux-x86-scalar/`](linux-x86-scalar/) measures the `x86_64` build with the B64Z scalar backend.

Each target page contains its result table, SVG and PNG figures, raw measurement table, and summary table.

## Compared operations

The four B64Z modes are `encode-memory`, `decode-memory`, `encode-streaming`, and `decode-streaming`.

Memory rows use complete-input adapters. Streaming rows use commands that read and write incrementally. A peer appears only in the mode selected for its command and adapter. Aklomp and GNU Coreutils appear in streaming rows. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 appear in memory rows.

## Method

Each row starts one command for one input. The timed process includes startup, file reads, allocation, Base64 work, and standard-output writes. Zebrac runs 20 measured samples after 5 warmups with a 15,000 ms duration ceiling. The reports use the geometric mean of 25 cases and show the huge-input result separately.

Byte checks run before timing. B64Z and every selected peer are compared with canonical padded Base64 bytes from Aklomp. Invalid-input checks apply only to B64Z because the selected peers accept different grammars.

These pages describe named command lines and builds on one Linux x86-64 host. They do not claim library-only instruction speed, a ranking on another host, or a result for an unlisted adapter.

The target choice changes the B64Z build only. Peer binaries keep their own native build and runtime dispatch settings. The scalar page therefore compares B64Z scalar code with those peer builds; it is not a scalar-for-every-peer instruction-set test.

## Run

The retained target scripts are:

```sh
bash bench/linux-x86-avx2/run.sh
bash bench/linux-x86-scalar/run.sh
```

The scripts require the Linux x86-64 toolchain and local qualification setup described in [`tools/tool.md`](../tools/tool.md). A publication run uses the default sample policy and byte checks.

## Tracked files

- `README.md` explains the target result and method.
- `measurements.tsv` contains one row for each measured command and case.
- `summary.tsv` contains the values used by the result table and figures.
- `figures/scaling.svg` and `figures/scaling.png` show throughput by nominal size.
- `figures/isocost.svg` and `figures/isocost.png` show time and peak-RSS ratios to B64Z.

The pages cover all 100 mode-and-case groups without creating one public page per input.
