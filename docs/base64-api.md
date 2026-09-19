# B64Z Base64 API

Status: **Active** (last updated: 2026-09-19)

## Scope

B64Z implements strict, padded RFC 4648 Base64. It uses the standard alphabet `A-Z`, `a-z`, `0-9`, `+`, and `/`. Decode requires complete four-byte groups, required padding, no whitespace, and zero discarded bits in the final padded group.

B64Z does not accept URL-safe, unpadded, MIME, or whitespace-tolerant input.

## Library API

The library exposes these names:

- `Error`
- `Backend` and `BACKEND`
- `encodedSize`
- `decodedSize`
- `encode`
- `decode`
- `encodeInPlace`
- `decodeInPlace`
- `Encoder`
- `Decoder`

The codec does not allocate. The caller supplies the input and output slices and uses the returned byte count to select the written output.

### Size helpers

`encodedSize(input_len)` returns the exact padded output length or `error.InputTooLarge` when the result cannot fit in `usize`.

`decodedSize(input)` checks the input length and final padding shape, then returns the exact decoded length. It returns `error.InvalidPadding` for an incomplete group, missing or misplaced padding, or an invalid padding shape. It does not validate alphabet bytes; `decode` performs that check.

### Disjoint-slice calls

`encode(input, output)` writes standard Base64 and returns the number of bytes written.

`decode(input, output)` writes decoded bytes and returns the number of bytes written.

For both functions:

- The input and output ranges must not overlap.
- The output must have at least the length returned by the matching size helper.
- The function returns `error.OverlappingBuffers` for overlapping ranges.
- The function returns `error.NoSpaceLeft` before writing when the output is too short.
- The function returns `error.InvalidCharacter` for a non-alphabet byte.
- Decode returns `error.InvalidPadding` for malformed padding or non-zero discarded bits.

The functions return `error.InputTooLarge` when a size calculation cannot fit in `usize`.

### In-place calls

`encodeInPlace(buffer, input_len)` encodes the first `input_len` bytes of `buffer` from the end of the input toward the beginning. The buffer must include the complete encoded capacity. It returns the encoded byte count.

`decodeInPlace(buffer)` decodes the complete contents of `buffer` from the beginning toward the end. It returns the decoded byte count.

These functions have separate names because their read and write order differs from the disjoint-slice calls.

### Stateful calls

`Encoder` retains up to two raw bytes between calls. `Encoder.update` and `Encoder.updateByte` write only complete three-byte groups. `Encoder.final` writes the final one- or two-byte group with padding.

`Decoder` retains up to three encoded bytes between calls. `Decoder.update` and `Decoder.updateByte` write only complete unpadded groups. A padded group remains in the decoder until `Decoder.final` checks and writes it.

The input and output slices passed to `Encoder.update` and `Decoder.update` must be disjoint.

If `update` or `updateByte` returns `error.NoSpaceLeft`, the encoder or decoder state and the output slice are unchanged. The caller can retry the same call with a larger output slice. `final` also leaves the carry state unchanged when its output slice is too short.

The stateful calls return `error.InvalidCharacter` or `error.InvalidPadding` when the input does not satisfy strict RFC 4648 rules. The caller must stop using the state after another error unless the API documents a retry rule for that error.

## Command line

The command is `custom-base64`. It accepts one input path and one of these modes:

```text
encode-memory
decode-memory
encode-streaming
decode-streaming
```

Memory modes read the complete input before encoding or decoding. Streaming modes read bounded chunks and retain only the stateful carry between chunks.

The command also accepts:

- `--chunk N`, a positive chunk size for streaming mode.
- `--iterations N`, a positive repeat count.
- `--raw`, which writes only encoded or decoded bytes to standard output.
- `--expected-probe HEX`, which checks the internal output probe and writes no result line.
- `--version`, which prints the B64Z version, selected backend, optimization mode, and target architecture.

Without `--raw` or `--expected-probe`, the command writes a result line describing the mode, byte counts, iteration count, output probe, and backend. Diagnostics go to standard error.

The command rejects the old `encode-one-shot` and `decode-one-shot` mode names.

## Backend selection

The build selects the backend at compile time. x86-64 builds with AVX2 use the AVX2 block functions; other builds use the scalar functions. The public function names, output bytes, errors, padding rules, and stateful buffer rules do not change with the selected backend.

## Checks

Run the library tests with:

```sh
zig build test --summary all
zig build test -Doptimize=ReleaseFast --summary all
```

The command-line modes and external byte checks are exercised by the benchmark and peer-check scripts described by the repository's benchmark pages.
