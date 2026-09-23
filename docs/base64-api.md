# B64Z Base64 API

Status: **Active** (last updated: 2026-09-22)

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

### Error order

Every decode entry point reports the same error for the same input, whatever the backend, the entry point, or the chunk sizes passed to the stateful decoder:

- Output capacity is checked before any write. `error.NoSpaceLeft` therefore comes before errors in the bytes that the call would decode.
- Groups are checked in input order, and the first defective group decides the error. Inside a group, `=` anywhere except a valid final padding position is `error.InvalidPadding`; any other non-alphabet byte is `error.InvalidCharacter`.
- A missing or incomplete final group is `error.InvalidPadding`, reported after the complete groups before it.

### Size helpers

`encodedSize(input_len)` returns the exact padded output length or `error.InputTooLarge` when the result cannot fit in `usize`.

`decodedSize(input)` checks the input length and final padding shape, then returns the exact decoded length. It returns `error.InvalidPadding` for an incomplete group, missing or misplaced padding, or an invalid padding shape such as `AA=A`. It does not validate alphabet bytes; `decode` performs that check.

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
- Decode errors follow the [error order](#error-order).

The functions return `error.InputTooLarge` when a size calculation cannot fit in `usize`.

### In-place calls

`encodeInPlace(buffer, input_len)` encodes the first `input_len` bytes of `buffer` from the end of the input toward the beginning. The buffer must include the complete encoded capacity. It returns the encoded byte count.

`decodeInPlace(buffer)` decodes the complete contents of `buffer` from the beginning toward the end. It returns the decoded byte count. After an error, the contents of `buffer` are unspecified.

These functions have separate names because their read and write order differs from the disjoint-slice calls. They use the same backend and produce the same bytes and errors as `encode` and `decode`.

### Stateful calls

`Encoder` retains up to two raw bytes between calls. `Encoder.update` and `Encoder.updateByte` write only complete three-byte groups. `Encoder.final` writes the final one- or two-byte group with padding.

`Decoder` retains up to three encoded bytes between calls, or four when the last complete group contains padding. `Decoder.update` and `Decoder.updateByte` write only complete unpadded groups. A padded group remains in the decoder until `Decoder.final` checks and writes it; any later input returns `error.InvalidPadding`.

The input and output slices passed to `Encoder.update` and `Decoder.update` must be disjoint. Both calls return `error.OverlappingBuffers` before changing any state when they overlap.

If `update` or `updateByte` returns `error.NoSpaceLeft`, the encoder or decoder state and the output slice are unchanged. The caller can retry the same call with a larger output slice. `final` also leaves the carry state unchanged when its output slice is too short.

The stateful calls return `error.InvalidCharacter` or `error.InvalidPadding` when the input does not satisfy strict RFC 4648 rules, following the [error order](#error-order). The caller must stop using the state after another error unless the API documents a retry rule for that error.

## Command line

The command is `custom-base64`. It accepts one input path and one of these modes, selected with `--mode`. Without `--mode`, it uses `encode-memory`.

```text
encode-memory
decode-memory
encode-streaming
decode-streaming
```

Memory modes read the complete input into one buffer and convert it in place with `encodeInPlace` or `decodeInPlace`; an encode buffer also holds the encoded output. On Linux, memory modes ask for transparent huge pages for regular-file buffers; other systems, and kernels that refuse the request, use ordinary pages with the same output. Streaming modes read bounded chunks and retain only the stateful carry between chunks.

The command also accepts:

- `--chunk N`, a positive chunk size for streaming mode.
- `--iterations N`, a positive repeat count. Each iteration reads the input file again.
- `--raw`, which writes only encoded or decoded bytes to standard output.
- `--expected-probe HEX`, which checks the internal output probe and writes no result line.
- `--version`, which prints the B64Z version, selected backend, optimization mode, and target architecture.

Without `--raw` or `--expected-probe`, the command writes a result line describing the mode, byte counts, iteration count, output probe, and backend. Diagnostics go to standard error.

The command rejects the old `encode-one-shot` and `decode-one-shot` mode names.

## Backend selection

The build selects the backend at compile time. x86-64 builds with AVX2 use the AVX2 block functions; other builds use the scalar functions. The public function names, output bytes, errors, padding rules, and stateful buffer rules do not change with the selected backend.

## Checks

Run the public behavior tests and the private SIMD kernel tests with:

```sh
zig build test --summary all
zig build test -Doptimize=ReleaseFast --summary all
```

The command-line modes and external byte checks are exercised by the benchmark and peer-check scripts described by the repository's benchmark pages.
