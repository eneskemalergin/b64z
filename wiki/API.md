# API reference

Function signatures, buffer requirements, errors, and backend selection for `src/base64.zig`.

## Encoding rules

B64Z implements strict, padded RFC 4648 Base64. It uses the standard alphabet `A-Z`, `a-z`, `0-9`, `+`, and `/`. Decode requires complete four-byte groups, required padding, no whitespace, and zero discarded bits in the final padded group.

B64Z does not accept URL-safe, unpadded, MIME, or whitespace-tolerant input. Padding is required only for a final binary group shorter than three bytes: `Zg==` and `Zm8=` need it; `Zm9v` does not.

## Library API

The codec does not allocate. The caller supplies the input and output slices and uses the returned byte count to select the written output.

```zig
pub fn encodedSize(input_len: usize) Error!usize
pub fn decodedSize(input: []const u8) Error!usize
pub fn encode(input: []const u8, output: []u8) Error!usize
pub fn decode(input: []const u8, output: []u8) Error!usize
pub fn encodeInPlace(buffer: []u8, input_len: usize) Error!usize
pub fn decodeInPlace(buffer: []u8) Error!usize
```

These are signatures, not complete declarations. `Encoder` and `Decoder` each expose `update`, `updateByte`, and `final`, described below. [Library examples](Library-Guide.md) show complete calls and buffer cleanup.

`Error` contains `InputTooLarge`, `InvalidCharacter`, `InvalidPadding`, `NoSpaceLeft`, and `OverlappingBuffers`. The sections below state which calls return each error.

### Error order

With sufficient output capacity, `decode`, `decodeInPlace`, and the stateful decoder report the same error for the same input across backends and chunk sizes:

- Disjoint calls reject overlapping slices first. Output capacity is checked before any write, so `error.NoSpaceLeft` comes before errors in the bytes that the call would decode.
- Groups are checked in input order, and the first defective group decides the error. In an unpadded group, a misplaced `=` gives `error.InvalidPadding`; another non-alphabet byte gives `error.InvalidCharacter`. A final padded group also checks padding positions and unused bits.
- A missing or incomplete final group is `error.InvalidPadding`, reported after the complete groups before it.

Malformed-input errors can occur after output has been written. Discard that output; only successful calls return a result length.

### Size helpers

`encodedSize(input_len)` returns the exact padded output length or `error.InputTooLarge` when the result cannot fit in `usize`.

`decodedSize(input)` checks that the input length is divisible by four and checks the final padding shape. For valid input it returns the exact decoded length. It returns `error.InvalidPadding` for an incomplete group or an invalid final padding shape such as `AA=A`.

It does not validate alphabet bytes, padding in earlier groups, or unused bits. A successful size calculation does not mean the input is valid. Its preliminary size checks also do not replace the decode error order.

### Disjoint-slice calls

`encode(input, output)` writes standard Base64 and returns the number of bytes written.

`decode(input, output)` writes decoded bytes and returns the number of bytes written.

For both functions:

- The input and output ranges must not overlap.
- The output must have at least the length returned by the matching size helper.
- The function returns `error.OverlappingBuffers` for overlapping ranges.
- The function returns `error.NoSpaceLeft` before writing when the output is too short.

`decode` returns `error.InvalidCharacter` for a non-alphabet byte and `error.InvalidPadding` for malformed padding or non-zero discarded bits, following the [error order](#error-order).

`encode` accepts arbitrary binary bytes; it does not report invalid characters or padding. It returns `error.InputTooLarge` when the encoded size cannot fit in `usize`.

### In-place calls

`encodeInPlace(buffer, input_len)` encodes the first `input_len` bytes of `buffer` from the end of the input toward the beginning. The buffer must include the complete encoded capacity. It returns the encoded byte count.

It returns `error.NoSpaceLeft` without changing the buffer if `input_len` exceeds the buffer length or the buffer cannot hold the encoded output. It returns `error.InputTooLarge` if the encoded length cannot fit in `usize`.

`decodeInPlace(buffer)` decodes the complete contents of `buffer` from the beginning toward the end. It returns the decoded byte count. After an error, the contents of `buffer` are unspecified.

These functions have separate names because their read and write order differs from the disjoint-slice calls. They use the same backend and produce the same bytes as `encode` and `decode`. `decodeInPlace` follows the same malformed-input error order as `decode`.

### Stateful calls

Both types expose these method signatures, with `Self` standing for `Encoder` or `Decoder`:

```zig
pub fn update(self: *Self, input: []const u8, output: []u8) Error!usize
pub fn updateByte(self: *Self, byte: u8, output: []u8) Error!usize
pub fn final(self: *Self, output: []u8) Error!usize
```

`Encoder` retains up to two raw bytes between calls. `Encoder.update` and `Encoder.updateByte` consume complete three-byte input groups and write four encoded bytes per group. `Encoder.final` writes the final one- or two-byte group with padding.

`Encoder.update` returns `error.InputTooLarge` if adding the carried bytes or calculating the required output length overflows `usize`.

`Decoder` retains up to three encoded bytes between calls, or four when the last complete group contains padding. `Decoder.update` and `Decoder.updateByte` write only complete unpadded groups. A padded group remains in the decoder until `Decoder.final` checks and writes it. While that group is retained, an update with more input returns `error.InvalidPadding`.

The input and output slices passed to `Encoder.update` and `Decoder.update` must be disjoint. Both calls return `error.OverlappingBuffers` before changing any state when they overlap.

If `update` or `updateByte` returns `error.NoSpaceLeft`, the encoder or decoder state and the output slice are unchanged. The caller can retry the same call with a larger output slice. `final` also leaves the carry state unchanged when its output slice is too short.

Decoder calls return `error.InvalidCharacter` or `error.InvalidPadding` when the input does not satisfy strict RFC 4648 rules, following the [error order](#error-order). The caller must stop using the state after another error unless the API documents a retry rule for that error. Encoder calls accept arbitrary binary bytes.

## Backend selection

`Backend` has the values `.avx2` and `.scalar`. The public constant `BACKEND` identifies the compiled codec.

The build selects the backend at compile time. x86-64 builds with AVX2 use the AVX2 block functions; other builds use the scalar functions. The public function names, output bytes, errors, padding rules, and stateful buffer rules do not change with the selected backend. An AVX2 binary does not fall back to scalar on a CPU without AVX2.

See [Getting started](Getting-Started.md#run-the-tests) for the test commands and [Command line](Command-Line.md) for the file converter's modes and options.
