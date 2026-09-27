# Library guide

Call B64Z with caller-owned buffers, or keep an `Encoder` or `Decoder` between input chunks.

## Add as a dependency

Use Zig 0.16.0 and the `b64z-VERSION-source.tar.gz` package. To create it from a B64Z checkout, run:

```sh
zig build source
```

This requires `tar` and writes the archive to `zig-out/`. In your application's directory, replace `SOURCE_ARCHIVE` with the archive's absolute path, or with the download URL of a published source archive:

```sh
zig fetch --save=b64z SOURCE_ARCHIVE
```

Zig records the package in your application's `build.zig.zon`. Fetch only the archive. Never pass a live checkout or `.` as the fetch input. The package contains the build files, Zig source and tests, and license notices; benchmarks, peer tools, and generated data stay in the repository.

In your application's `build.zig`, use its existing `target`, `optimize`, and executable values:

```zig
const b64z = b.dependency("b64z", .{
    .target = target,
    .optimize = optimize,
});
exe.root_module.addImport("base64", b64z.module("base64"));
```

Your Zig code can now use `@import("base64")`. The consumer chooses the target and optimization mode. Importing this module does not build the CLI or run B64Z's tests. The [API reference](API) describes backend selection and every public call.

## Run the examples

Each example below is a complete Zig test file. In a B64Z checkout, save the example as `example.zig` beside `build.zig`, then run:

```sh
zig test --dep base64 -Mroot=example.zig -Mbase64=src/base64.zig
```

This command makes `src/base64.zig` available as `@import("base64")`. It does not build or call the CLI. The [API reference](API) lists every public function and its buffer and error rules.

## Separate input and output

The caller allocates storage and frees it. B64Z returns the length of the result in that storage. The input and output slices must not overlap.

```zig
//! Encodes and decodes using caller-allocated buffers.
const std = @import("std");
const base64 = @import("base64");

test "[unit] - [example]: converts separate buffers" {
    const allocator = std.testing.allocator;
    const input = "hello";
    const encoded = try allocator.alloc(u8, try base64.encodedSize(input.len));
    defer allocator.free(encoded);

    const encoded_len = try base64.encode(input, encoded);
    try std.testing.expectEqualStrings("aGVsbG8=", encoded[0..encoded_len]);

    const decoded = try allocator.alloc(u8, try base64.decodedSize(encoded[0..encoded_len]));
    defer allocator.free(decoded);

    const decoded_len = try base64.decode(encoded[0..encoded_len], decoded);
    try std.testing.expectEqualStrings(input, decoded[0..decoded_len]);
}
```

`decodedSize` checks the encoded length and final padding shape. It does not validate the complete input. You must still handle errors from `decode`.

## Convert in place

Encoding needs spare room because Base64 is larger than the binary input. Decoding uses the encoded buffer's existing capacity. Pass only the encoded bytes to `decodeInPlace`, not the unused end of a larger allocation.

```zig
//! Encodes and decodes within one caller-owned buffer.
const std = @import("std");
const base64 = @import("base64");

test "[unit] - [example]: converts in place" {
    var buffer: [8]u8 = undefined;
    @memcpy(buffer[0..5], "hello");

    const encoded_len = try base64.encodeInPlace(&buffer, 5);
    try std.testing.expectEqualStrings("aGVsbG8=", buffer[0..encoded_len]);

    const decoded_len = try base64.decodeInPlace(buffer[0..encoded_len]);
    try std.testing.expectEqualStrings("hello", buffer[0..decoded_len]);
}
```

After a decode error, discard the result. The buffer may have been changed before the invalid group was found.

## Reuse streaming buffers

Start with `Encoder{}` or `Decoder{}`. An update can return zero while retaining an incomplete group. Consume the returned output slice before reusing the buffer. Call `final` after the last input chunk; a padded decode group is not written until that call succeeds.

```zig
//! Converts split input while reusing small output buffers.
const std = @import("std");
const base64 = @import("base64");

test "[unit] - [example]: carries bytes between chunks" {
    var encoder: base64.Encoder = .{};
    var encoded: [4]u8 = undefined;

    try std.testing.expectEqual(@as(usize, 0), try encoder.update("h", &encoded));
    const body_len = try encoder.update("ell", &encoded);
    try std.testing.expectEqualStrings("aGVs", encoded[0..body_len]);
    try std.testing.expectEqual(@as(usize, 0), try encoder.update("o", &encoded));
    const tail_len = try encoder.final(&encoded);
    try std.testing.expectEqualStrings("bG8=", encoded[0..tail_len]);

    var decoder: base64.Decoder = .{};
    var decoded: [3]u8 = undefined;

    try std.testing.expectEqual(@as(usize, 0), try decoder.update("aG", &decoded));
    const decoded_body_len = try decoder.update("VsbG8=", &decoded);
    try std.testing.expectEqualStrings("hel", decoded[0..decoded_body_len]);
    const decoded_tail_len = try decoder.final(&decoded);
    try std.testing.expectEqualStrings("lo", decoded[0..decoded_tail_len]);
}
```

The output buffer must fit all complete groups written by that call, including any carried input. On `error.NoSpaceLeft`, state and output are unchanged; retry the same input with more output space. The call does not report partial input consumption. After a malformed-input error, stop processing that message and discard its output.

`updateByte` accepts one byte with the same carry and retry rules. Use slice updates for chunks already available together.
