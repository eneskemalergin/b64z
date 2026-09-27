# Benchmarking

Results, inputs, and measurement method for the two Linux x86-64 command-line comparisons.

- The [AVX2 report](https://github.com/eneskemalergin/b64z/blob/main/bench/linux-x86-avx2/README.md) measures the `haswell` build with the B64Z AVX2 backend.
- The [scalar report](https://github.com/eneskemalergin/b64z/blob/main/bench/linux-x86-scalar/README.md) measures the `x86_64` build with the B64Z scalar backend.

Each target page contains its result table, light and dark SVG figures, per-command measurement table, and summary table.

## Status of these results

The retained pages were generated on 2026-09-23 from source commit `3309e5b8a7b27b359bc3fed8f6524ea0a7d6a79b`; both record `git_changes=no`. They include the current AVX2 kernels, in-place memory modes, and streaming decoder.

The Aklomp executable in both pages was built with `AVX2_CFLAGS=-mavx2`; upstream runtime dispatch selects AVX2 on this host. The scalar page compares B64Z's scalar build with peers using their native build and runtime dispatch settings.

## Compared operations

The four B64Z modes are `encode-memory`, `decode-memory`, `encode-streaming`, and `decode-streaming`.

In a mode name, `memory` means complete-input processing, not the measured memory value. B64Z reads the complete input into one buffer and converts it in place; for encoding, that buffer also holds the encoded output. The peer memory adapters keep separate input and output buffers. `Streaming` means incremental processing through fixed input and output buffers. A peer appears only in the mode selected for its command and adapter. Aklomp and GNU Coreutils appear in streaming rows. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 appear in memory rows.

`Peak RSS` is the per-sample maximum resident set size reported by Zebrac for the timed process. The reports use the mean of those per-sample peaks. It includes the executable, runtime, file I/O buffers, codec state, and resident input or output allocations. It is not the size of one codec buffer.

## Input sizes

The five nominal sizes are `tiny` = 256 B, `small` = 16 KiB, `medium` = 1 MiB, `large` = 8 MiB, and `huge` = 32 MiB. Each size has five forms: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib.

These are generated inputs. General cases contain deterministic bytes. The mzML cases contain little-endian float32 or float64 arrays, either uncompressed or compressed with zlib level 6 before Base64 conversion. They represent binary-array storage used in mzML, not complete XML documents or measured instrument data. Compression and decompression are outside the timed command.

For zlib cases, the size label describes the array before compression, not the smaller file passed to the encoder. Decode reads padded Base64 of the corresponding binary file. The measurement table records actual input and output byte counts; throughput uses the binary byte count, not the nominal size label or the encoded byte count.

## Method

> [!NOTE]
> **Peer settings and memory allocation**
>
> Peers retain the build and CPU dispatch settings described in [Benchmark tools](Benchmark-Tools.md), including AVX2 for the tools built to use it. The scalar target changes B64Z only.
>
> B64Z's memory modes convert in place and request Linux transparent huge pages for large buffers. Our peer memory adapters use separate input and output buffers; we did not add huge-page advice to them. The reported command time and peak RSS include these allocation differences, along with startup, file I/O, and codec work.

Each row starts one command for one input. B64Z streaming rows pass `--chunk 8191` for encoding and `--chunk 4093` for decoding, so each 64 KiB read is converted in several `update` calls. Memory rows read the complete input into one buffer and convert it in place; they do not pass `--chunk`. Peer memory adapters use separate input and output buffers. The timed process includes startup, file reads, allocation, Base64 work, and standard-output writes. Zebrac runs 20 measured samples after 5 warmups with a 15,000 ms duration ceiling. The reports use the geometric mean of 25 cases and show the general huge-input result separately.

Byte checks run before timing. B64Z and every selected peer are compared with canonical padded Base64 bytes from Aklomp. Invalid-input checks apply only to B64Z because the selected peers accept different grammars.

These pages describe named command lines and builds on one Linux x86-64 host. They do not claim library-only instruction speed, a ranking on another host, or a result for an unlisted adapter.

The target choice changes the B64Z build only. Peer binaries keep their own native build and runtime dispatch settings. The scalar page therefore compares B64Z scalar code with those peer builds; it is not a scalar-for-every-peer instruction-set test.

A measurement or report-writing run refuses a worktree with project changes. Generated benchmark pages do not count as project changes, so the AVX2 and scalar pages can be measured in separate runs from the same commit.

## Read the figures

Time and peak-RSS ratios divide a peer's measurement by B64Z's measurement for the same input and mode. B64Z is `1.0x`; a lower value means less time or less resident memory. The summary labels each peer directly and shows the geometric mean of the 25 case ratios as a marker and a number. Its whiskers show the middle 50% of cases, not confidence intervals on repeated measurements. Both summary panels use the same logarithmic ratio scale.

The scaling figures group throughput by nominal size and plot those byte sizes on a logarithmic horizontal axis. Throughput uses a shared logarithmic vertical scale across all four panels; each point is the geometric mean of the five input forms at that size. Lines connect the measured sizes.

The isocost figures place the time ratio on the horizontal axis and the peak-RSS ratio on the vertical axis, with shared logarithmic scales across all four panels. Small markers show individual cases; larger markers show geometric means, with bars for the middle 50% of cases. A line labelled `C` joins points with the same product, `time ratio * RSS ratio`. That product treats the two ratios equally; it does not account for a particular machine's memory limit or cost.

The SVGs retain vector lines and selectable text. Each tool has a consistent color and marker shape in both themes, and throughput lines also use distinct dash patterns.

## Run

The retained target scripts are:

```sh
bash bench/linux-x86-avx2/run.sh
bash bench/linux-x86-scalar/run.sh
```

The scripts require Linux x86-64, Zig 0.16.0, Python 3.10 or newer, the selected peer executables, Zebrac with access to Linux performance counters, and gnuplot. [Benchmark tools](Benchmark-Tools.md) lists peer builds, adapters, and byte-check commands. The runner builds B64Z, not the peers.

A publication run uses the default sample policy and byte checks. `--skip-benchmarks --skip-report` builds the selected B64Z target and runs byte checks without Zebrac or gnuplot. The file cache is warm after verification; the runner does not pin a CPU or flush the page cache.

## Result files

- Each target's `README.md` records its result and run conditions. This wiki page describes the shared method.
- `measurements.tsv` contains one row for each measured command and case, with sample counts, means, and quartiles. It does not contain the individual sample observations.
- `summary.tsv` contains the values used by the result table and figures.
- `figures/scaling-light.svg` and `figures/scaling-dark.svg` show throughput by nominal size.
- `figures/isocost-light.svg` and `figures/isocost-dark.svg` show one dot per input case, geometric means, peak-RSS ratios to B64Z, and combined-cost curves.
- `figures/summary-light.svg` and `figures/summary-dark.svg` in the AVX2 report show the summary used by the main README.

The pages cover all 100 mode-and-case groups without creating one public page per input.

To redraw only the figures from the retained measurements, including while editing the plot styles, run:

```sh
python3 bench/report.py render --target linux-x86-avx2 --figures-only
python3 bench/report.py render --target linux-x86-scalar --figures-only
```

This leaves the measurement files, summary tables, and report metadata unchanged.
