# B64Z

B64Z is a strict padded RFC 4648 Base64 library and file converter written in Zig.

The library encodes and decodes caller-owned byte slices without allocating. It has separate calls for disjoint buffers, in-place conversion, and input that arrives in chunks. The command-line program is named `custom-base64`.

## Start here

- [Getting started](Getting-Started): build the command with Zig 0.16.0 and check its output.
- [Command line](Command-Line): choose a conversion mode, redirect output, and handle errors.
- [Library guide](Library-Guide): encode, decode, convert in place, and reuse streaming buffers.
- [API reference](API): look up function signatures, output capacity, and error behavior.
- [Development](Development): find the source files, run tests, and contribute code or documentation.

## Read the benchmarks

[Benchmarking](Benchmarking) links the Linux x86-64 AVX2 and scalar results and explains the input sizes, commands, and measurements. [Benchmark tools](Benchmark-Tools) describes the selected peers, build settings, and adapters.

## Current behavior

- The alphabet is `A-Z`, `a-z`, `0-9`, `+`, and `/`. Padding is required when the last binary group has fewer than three bytes.
- Decode rejects whitespace, URL-safe characters, malformed padding, and non-zero unused bits in the final padded group. Encoded output has no line wrapping or trailing newline.
- The CLI offers whole-input conversion in one buffer and streaming conversion through fixed buffers. Both write the same bytes for valid input.
- An x86-64 build with AVX2 enabled uses the AVX2 codec. Other builds select the scalar codec at compile time. There is no runtime CPU dispatch.

B64Z is in active development. The build requires Zig 0.16.0. The retained runtime measurements cover Linux x86-64; selecting the scalar codec does not establish that the CLI has been tested on every operating system or architecture.
