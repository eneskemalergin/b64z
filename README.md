# B64Z

Status: Active development.

B64Z is a strict RFC 4648 Base64 codec with caller-owned output buffers, memory and stateful streaming APIs, and an AVX2 fast path on x86-64.

Read the [Base64 API reference](docs/base64-api.md) for library, command-line, buffer, error, and backend rules.

The library source is [`src/base64.zig`](src/base64.zig). The command-line adapter is [`src/main.zig`](src/main.zig).

## Checks

Use Zig 0.16:

```sh
zig build test --summary all
zig build test -Dcpu=native -Doptimize=ReleaseFast --summary all
```

## Benchmark summary

The figure summarizes the Linux x86-64 AVX2 report. See the [benchmark README](bench/README.md) for the inputs, commands, and measurement method.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="bench/linux-x86-avx2/figures/summary-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="bench/linux-x86-avx2/figures/summary-light.svg">
    <img src="bench/linux-x86-avx2/figures/summary-light.svg" alt="B64Z Linux x86-64 AVX2 benchmark summary showing wall-time and peak-RSS ratios for four encoding and decoding modes" width="100%">
  </picture>
</p>

Detailed results are in the [AVX2 report](bench/linux-x86-avx2/) and [scalar report](bench/linux-x86-scalar/). They measure named command lines on one Linux x86-64 host; they do not describe every library or operating system.
