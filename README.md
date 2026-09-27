<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img src="assets/logo-readme.svg" alt="B64Z" width="200">
</p>

<p align="center">
  <strong>Strict Base64 for Zig, with bounded-memory file conversion.</strong>
</p>

<p align="center">
  <a href="wiki/Getting-Started.md"><img src="https://img.shields.io/badge/Zig-0.16.0-F7A41D?style=flat-square&amp;logo=zig&amp;logoColor=white" alt="Build with Zig 0.16.0"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.1.0-8B5CF6?style=flat-square" alt="Source version 0.1.0"></a>
  <a href="https://github.com/eneskemalergin/b64z/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/eneskemalergin/b64z/ci.yml?branch=main&amp;style=flat-square&amp;label=CI&amp;logo=githubactions" alt="CI status"></a>
  <a href="#where-it-stands"><img src="https://img.shields.io/badge/status-development-C17D10?style=flat-square" alt="Status: development"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-4B9D6E?style=flat-square" alt="MIT License"></a>
</p>

<p align="center">
  <a href="wiki/Home.md"><img src="https://img.shields.io/badge/wiki-documentation-2563eb?style=flat-square" alt="Wiki documentation"></a>
  <a href="wiki/API.md"><img src="https://img.shields.io/badge/API-reference-7c3aed?style=flat-square" alt="API reference"></a>
  <a href="wiki/Benchmarking.md"><img src="https://img.shields.io/badge/benchmarks-reports-f59e0b?style=flat-square" alt="Benchmark reports"></a>
</p>

---

I built B64Z for Base64 work where memory use matters alongside speed. It is a library and a command-line converter:

- The library encodes and decodes buffers you supply, without allocating. Use separate input and output buffers, convert in place, or feed chunks through an `Encoder` or `Decoder`.
- The command converts a whole file in one buffer or streams it through fixed buffers. Streaming memory does not grow with file length.

B64Z uses standard padded RFC 4648 Base64. Decode rejects whitespace, URL-safe characters, malformed padding, and non-zero unused bits. There is no forgiving decode mode.

<p align="center">
  <a href="bench/linux-x86-avx2/README.md">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="bench/linux-x86-avx2/figures/summary-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="bench/linux-x86-avx2/figures/summary-light.svg">
      <img src="bench/linux-x86-avx2/figures/summary-light.svg" alt="Peer-to-B64Z wall-time and peak-RSS ratios for memory and streaming conversion on Linux x86-64 with AVX2" width="100%">
    </picture>
  </a>
</p>
<p align="center"><sub>File-conversion time and peak process memory on one Linux x86-64 host. Markers show geometric means; whiskers show the middle 50% of input cases. B64Z is the 1.0x reference; lower is better. Open the report for absolute values and run conditions.</sub></p>

## Where it stands

B64Z is in active development. AVX2 acceleration is available on x86-64; other builds select the scalar codec. Backend selection happens at compile time, so an AVX2 binary does not fall back on an older CPU. The current tests and benchmark reports cover Linux x86-64, not every system the scalar code might compile for.

The benchmarks time complete commands, including startup, file reads, allocation, and output. They do not rank the libraries' inner loops. The [AVX2 report](bench/linux-x86-avx2/README.md), [scalar report](bench/linux-x86-scalar/README.md), and [measurement method](wiki/Benchmarking.md) keep those comparisons explicit.

## Start

Build from the repository root with Zig 0.16.0:

```sh
zig build -Dcpu=native -Doptimize=ReleaseFast -Dstrip=true
./zig-out/bin/custom-base64 --mode encode-streaming input.bin > encoded.b64
./zig-out/bin/custom-base64 --mode decode-streaming encoded.b64 > decoded.bin
```

Use different input and output paths. This build targets the current CPU. The [getting-started guide](wiki/Getting-Started.md) covers scalar builds, a round-trip example, and tests.

## Documentation

The [wiki](wiki/Home.md) contains the guides and reference:

[Command line](wiki/Command-Line.md) | [Library examples](wiki/Library-Guide.md) | [API reference](wiki/API.md) | [Benchmark method](wiki/Benchmarking.md) | [Benchmark tools](wiki/Benchmark-Tools.md) | [Development](wiki/Development.md)

## License

MIT. See [LICENSE](LICENSE).

The AVX2 kernels include code adapted from Aklomp Base64 under BSD-2-Clause; see [third-party notices](THIRD_PARTY_NOTICES.md).

---

<p align="center"><em>Narrow channel flows;<br>
three expand to four, return,<br>
not one droplet lost.</em></p>
