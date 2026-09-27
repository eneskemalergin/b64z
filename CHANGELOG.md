# Changelog

Changes by version. Publication dates are added when a version is released.

## [Unreleased]

## [0.1.0]

Initial version of B64Z, built with Zig 0.16.0.

### Added

- Strict padded RFC 4648 encoding and decoding, with scalar and x86-64 AVX2 backends selected at compile time.
- A library that writes into caller-owned buffers without allocating: sizing helpers, separate-buffer calls, in-place conversion, and stateful `Encoder` and `Decoder` types.
- A Zig package exporting the `base64` module, with a small source archive separate from the two CLI binary archives.
- Four file-conversion modes: `encode-memory`, `decode-memory`, `encode-streaming`, and `decode-streaming`. Streaming uses fixed buffers; memory modes convert the whole input in one buffer.
- Tests for exact output, malformed input, error order, short buffers, overlap, in-place conversion, streaming chunks, and CLI behavior.
- Linux x86-64 scalar and AVX2 benchmark reports for command wall time, throughput, and peak RSS.
- Wiki guides, API reference, and the MIT license.
- CI checks for both backends in Debug and ReleaseFast, tested release archives, workflow checks with actionlint and zizmor, and monthly GitHub Actions dependency updates.
