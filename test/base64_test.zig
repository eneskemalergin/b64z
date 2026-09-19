//! Public Base64 behavior tests for exact output, strict rejection, and buffer limits.

const std = @import("std");
const base64 = @import("base64");

test "[unit] - [encoder]: matches RFC 4648 vectors" {
    const cases = [_]struct { input: []const u8, expected: []const u8 }{
        .{ .input = "", .expected = "" },
        .{ .input = "f", .expected = "Zg==" },
        .{ .input = "fo", .expected = "Zm8=" },
        .{ .input = "foo", .expected = "Zm9v" },
        .{ .input = "foob", .expected = "Zm9vYg==" },
        .{ .input = "fooba", .expected = "Zm9vYmE=" },
        .{ .input = "foobar", .expected = "Zm9vYmFy" },
    };

    for (cases) |case| {
        var output: [32]u8 = undefined;
        const written = try base64.encode(case.input, &output);
        try std.testing.expectEqualSlices(u8, case.expected, output[0..written]);
        try std.testing.expectEqual(case.expected.len, try base64.encodedSize(case.input.len));
    }
}

test "[property] - [encoder]: matches a scalar reference across SIMD tails" {
    var input: [193]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 73 + 19);

    var output: [260]u8 = undefined;
    var expected: [260]u8 = undefined;
    for (0..input.len + 1) |length| {
        const expected_len = referenceEncode(input[0..length], &expected);
        const actual_len = try base64.encode(input[0..length], &output);
        try std.testing.expectEqual(expected_len, actual_len);
        try std.testing.expectEqualSlices(u8, expected[0..expected_len], output[0..actual_len]);
    }
}

test "[property] - [decoder]: round trips arbitrary bytes and matches the standard library" {
    var input: [4096]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 29 + (index >> 3) + 7);

    var encoded: [5500]u8 = undefined;
    var decoded: [4096]u8 = undefined;
    var standard_decoded: [4096]u8 = undefined;
    const lengths = [_]usize{ 0, 1, 2, 3, 4, 11, 12, 13, 31, 32, 33, 47, 48, 49, 63, 64, 65, 95, 96, 97, 127, 128, 129, 1023, 1024, 1025, 4095, 4096 };

    for (lengths) |length| {
        const encoded_len = try base64.encode(input[0..length], &encoded);
        const decoded_len = try base64.decode(encoded[0..encoded_len], &decoded);
        try std.testing.expectEqual(length, decoded_len);
        try std.testing.expectEqualSlices(u8, input[0..length], decoded[0..decoded_len]);

        const standard_len = try std.base64.standard.Decoder.calcSizeForSlice(encoded[0..encoded_len]);
        try std.base64.standard.Decoder.decode(
            standard_decoded[0..standard_len],
            encoded[0..encoded_len],
        );
        try std.testing.expectEqualSlices(u8, standard_decoded[0..standard_len], decoded[0..decoded_len]);
    }
}

test "[edge] - [size helpers]: report exact empty and padded lengths" {
    try std.testing.expectEqual(@as(usize, 0), try base64.encodedSize(0));
    try std.testing.expectEqual(@as(usize, 4), try base64.encodedSize(1));
    try std.testing.expectEqual(@as(usize, 8), try base64.encodedSize(4));
    try std.testing.expectEqual(@as(usize, 0), try base64.decodedSize(""));
    try std.testing.expectEqual(@as(usize, 1), try base64.decodedSize("AA=="));
    try std.testing.expectEqual(@as(usize, 2), try base64.decodedSize("AAA="));
    try std.testing.expectEqual(@as(usize, 3), try base64.decodedSize("AAAA"));

    try std.testing.expectError(error.InvalidPadding, base64.decodedSize("A"));
    try std.testing.expectError(error.InvalidPadding, base64.decodedSize("A==="));
    try std.testing.expectError(error.InvalidPadding, base64.decodedSize("AA="));
    try std.testing.expectError(error.InputTooLarge, base64.encodedSize(std.math.maxInt(usize)));
}

test "[failure] - [buffers]: rejects short and overlapping output slices" {
    var output: [8]u8 = undefined;
    try std.testing.expectError(error.NoSpaceLeft, base64.encode("foobar", output[0..7]));
    try std.testing.expectError(error.NoSpaceLeft, base64.decode("Zm9vYmFy", output[0..5]));

    var shared: [16]u8 = undefined;
    try std.testing.expectError(error.OverlappingBuffers, base64.encode(shared[0..3], shared[0..4]));
    @memcpy(shared[0..4], "Zm8=");
    try std.testing.expectError(error.OverlappingBuffers, base64.decode(shared[0..4], shared[0..2]));
}

test "[failure] - [streaming]: update retries after NoSpaceLeft" {
    var output = [_]u8{0xaa} ** 4;

    var encoder: base64.Encoder = .{};
    try std.testing.expectEqual(@as(usize, 0), try encoder.update("f", output[0..0]));
    try std.testing.expectError(error.NoSpaceLeft, encoder.update("oo", output[0..3]));
    try std.testing.expectEqualSlices(u8, &([_]u8{0xaa} ** 4), &output);
    try std.testing.expectEqual(@as(usize, 4), try encoder.update("oo", &output));
    try std.testing.expectEqualSlices(u8, "Zm9v", &output);

    output = [_]u8{0xaa} ** 4;
    var decoder: base64.Decoder = .{};
    try std.testing.expectEqual(@as(usize, 0), try decoder.update("Z", output[0..0]));
    try std.testing.expectError(error.NoSpaceLeft, decoder.update("m9v", output[0..2]));
    try std.testing.expectEqualSlices(u8, &([_]u8{0xaa} ** 4), &output);
    try std.testing.expectEqual(@as(usize, 3), try decoder.update("m9v", output[0..3]));
    try std.testing.expectEqualSlices(u8, "foo", output[0..3]);
}

test "[failure] - [streaming]: byte update retries after NoSpaceLeft" {
    var output = [_]u8{0xaa} ** 4;

    var encoder: base64.Encoder = .{};
    try std.testing.expectEqual(@as(usize, 0), try encoder.updateByte('f', output[0..0]));
    try std.testing.expectEqual(@as(usize, 0), try encoder.updateByte('o', output[0..3]));
    try std.testing.expectError(error.NoSpaceLeft, encoder.updateByte('o', output[0..3]));
    try std.testing.expectEqualSlices(u8, &([_]u8{0xaa} ** 4), &output);
    try std.testing.expectEqual(@as(usize, 4), try encoder.updateByte('o', &output));
    try std.testing.expectEqualSlices(u8, "Zm9v", &output);

    output = [_]u8{0xaa} ** 4;
    var decoder: base64.Decoder = .{};
    try std.testing.expectEqual(@as(usize, 0), try decoder.updateByte('Z', output[0..0]));
    try std.testing.expectEqual(@as(usize, 0), try decoder.updateByte('m', output[0..0]));
    try std.testing.expectEqual(@as(usize, 0), try decoder.updateByte('9', output[0..0]));
    try std.testing.expectError(error.NoSpaceLeft, decoder.updateByte('v', output[0..2]));
    try std.testing.expectEqualSlices(u8, &([_]u8{0xaa} ** 4), &output);
    try std.testing.expectEqual(@as(usize, 3), try decoder.updateByte('v', output[0..3]));
    try std.testing.expectEqualSlices(u8, "foo", output[0..3]);
}

test "[failure] - [decoder]: rejects malformed, noncanonical, and wrapped input" {
    const cases = [_]struct { input: []const u8, expected: anyerror }{
        .{ .input = "A", .expected = error.InvalidPadding },
        .{ .input = "AAA", .expected = error.InvalidPadding },
        .{ .input = "AA", .expected = error.InvalidPadding },
        .{ .input = "AA$=", .expected = error.InvalidCharacter },
        .{ .input = "AA-_", .expected = error.InvalidCharacter },
        .{ .input = "=AAA", .expected = error.InvalidPadding },
        .{ .input = "A=AA", .expected = error.InvalidPadding },
        .{ .input = "AA=A", .expected = error.InvalidPadding },
        .{ .input = "A===", .expected = error.InvalidPadding },
        .{ .input = "====", .expected = error.InvalidPadding },
        .{ .input = "AA\n=", .expected = error.InvalidCharacter },
        .{ .input = "AB==", .expected = error.InvalidPadding },
        .{ .input = "ABC=", .expected = error.InvalidPadding },
        .{ .input = "Zm=8", .expected = error.InvalidPadding },
        .{ .input = "AA?=", .expected = error.InvalidCharacter },
    };

    var output: [64]u8 = undefined;
    for (cases) |case| try std.testing.expectError(case.expected, base64.decode(case.input, &output));
}

test "[failure] - [decoder]: rejects invalid bytes in SIMD-sized runs" {
    var input: [40]u8 = undefined;
    @memset(&input, 'A');
    var output: [32]u8 = undefined;

    input[17] = '#';
    try std.testing.expectError(error.InvalidCharacter, base64.decode(&input, &output));
    input[17] = '=';
    try std.testing.expectError(error.InvalidPadding, base64.decode(&input, &output));
}

test "[property] - [in-place]: preserves strict output for every length" {
    var input: [193]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 73 + 19);

    var expected: [260]u8 = undefined;
    var work: [260]u8 = undefined;
    for (0..input.len + 1) |length| {
        const expected_len = try base64.encode(input[0..length], &expected);
        @memcpy(work[0..length], input[0..length]);
        const encoded_len = try base64.encodeInPlace(&work, length);
        try std.testing.expectEqual(expected_len, encoded_len);
        try std.testing.expectEqualSlices(u8, expected[0..expected_len], work[0..encoded_len]);

        @memcpy(work[0..encoded_len], expected[0..encoded_len]);
        const decoded_len = try base64.decodeInPlace(work[0..encoded_len]);
        try std.testing.expectEqual(length, decoded_len);
        try std.testing.expectEqualSlices(u8, input[0..length], work[0..decoded_len]);
    }
    try std.testing.expectError(error.NoSpaceLeft, base64.encodeInPlace(work[0..3], 3));
}

test "[property] - [decoder]: classifies every byte at every group position" {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    var input = [_]u8{ 'A', 'A', 'A', 'A' };
    var output: [3]u8 = undefined;

    for (0..4) |position| {
        for (0..256) |value| {
            const byte: u8 = @intCast(value);
            input[position] = byte;
            const result = base64.decode(&input, &output);
            if (std.mem.indexOfScalar(u8, alphabet, byte) != null) {
                try std.testing.expectEqual(@as(usize, 3), try result);
            } else if (position == 3 and byte == '=') {
                try std.testing.expectEqual(@as(usize, 2), try result);
            } else {
                _ = result catch |err| switch (err) {
                    error.InvalidCharacter, error.InvalidPadding => 0,
                    else => return err,
                };
            }
        }
        input[position] = 'A';
    }
}

test "[unit] - [decoder]: accepts only canonical final groups" {
    var output: [3]u8 = undefined;
    try std.testing.expectEqual(@as(usize, 1), try base64.decode("AA==", &output));
    try std.testing.expectEqual(@as(usize, 2), try base64.decode("AAA=", &output));
    try std.testing.expectEqual(@as(usize, 3), try base64.decode("AAAA", &output));
    try std.testing.expectEqualSlices(u8, &[_]u8{ 0, 0, 0 }, output[0..3]);
}

test "[property] - [streaming]: state survives every chunk boundary" {
    var input: [193]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 73 + 19);

    var expected_encoded: [260]u8 = undefined;
    const expected_encoded_len = try base64.encode(&input, &expected_encoded);
    var encoded: [260]u8 = undefined;
    var decoded: [193]u8 = undefined;

    for (1..33) |chunk_size| {
        var encoder: base64.Encoder = .{};
        var encoded_len: usize = 0;
        var input_index: usize = 0;
        while (input_index < input.len) {
            const chunk_len = @min(chunk_size, input.len - input_index);
            encoded_len += try encoder.update(
                input[input_index..][0..chunk_len],
                encoded[encoded_len..],
            );
            input_index += chunk_len;
        }
        encoded_len += try encoder.final(encoded[encoded_len..]);
        try std.testing.expectEqual(expected_encoded_len, encoded_len);
        try std.testing.expectEqualSlices(u8, expected_encoded[0..expected_encoded_len], encoded[0..encoded_len]);

        var decoder: base64.Decoder = .{};
        var decoded_len: usize = 0;
        var encoded_index: usize = 0;
        while (encoded_index < encoded_len) {
            const chunk_len = @min(chunk_size, encoded_len - encoded_index);
            decoded_len += try decoder.update(
                encoded[encoded_index..][0..chunk_len],
                decoded[decoded_len..],
            );
            encoded_index += chunk_len;
        }
        decoded_len += try decoder.final(decoded[decoded_len..]);
        try std.testing.expectEqual(input.len, decoded_len);
        try std.testing.expectEqualSlices(u8, &input, decoded[0..decoded_len]);
    }
}

test "[property] - [streaming]: byte updates match block updates" {
    var input: [97]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 41 + 3);

    var expected: [132]u8 = undefined;
    const expected_len = try base64.encode(&input, &expected);
    var encoded: [132]u8 = undefined;
    var encoder: base64.Encoder = .{};
    var encoded_len: usize = 0;
    for (input) |byte| encoded_len += try encoder.updateByte(byte, encoded[encoded_len..]);
    encoded_len += try encoder.final(encoded[encoded_len..]);
    try std.testing.expectEqual(expected_len, encoded_len);
    try std.testing.expectEqualSlices(u8, expected[0..expected_len], encoded[0..encoded_len]);

    var decoded: [97]u8 = undefined;
    var decoder: base64.Decoder = .{};
    var decoded_len: usize = 0;
    for (encoded[0..encoded_len]) |byte| decoded_len += try decoder.updateByte(byte, decoded[decoded_len..]);
    decoded_len += try decoder.final(decoded[decoded_len..]);
    try std.testing.expectEqual(input.len, decoded_len);
    try std.testing.expectEqualSlices(u8, &input, decoded[0..decoded_len]);
}

fn referenceEncode(input: []const u8, output: []u8) usize {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    var input_index: usize = 0;
    var output_index: usize = 0;
    while (input.len - input_index >= 3) {
        const first = input[input_index];
        const second = input[input_index + 1];
        const third = input[input_index + 2];
        const bits = (@as(u32, first) << 16) | (@as(u32, second) << 8) | third;
        output[output_index] = alphabet[@intCast((bits >> 18) & 0x3f)];
        output[output_index + 1] = alphabet[@intCast((bits >> 12) & 0x3f)];
        output[output_index + 2] = alphabet[@intCast((bits >> 6) & 0x3f)];
        output[output_index + 3] = alphabet[@intCast(bits & 0x3f)];
        input_index += 3;
        output_index += 4;
    }
    const remaining = input.len - input_index;
    if (remaining == 1) {
        const first = input[input_index];
        output[output_index] = alphabet[first >> 2];
        output[output_index + 1] = alphabet[(first & 0x03) << 4];
        output[output_index + 2] = '=';
        output[output_index + 3] = '=';
        output_index += 4;
    } else if (remaining == 2) {
        const first = input[input_index];
        const second = input[input_index + 1];
        output[output_index] = alphabet[first >> 2];
        output[output_index + 1] = alphabet[((first & 0x03) << 4) | (second >> 4)];
        output[output_index + 2] = alphabet[(second & 0x0f) << 2];
        output[output_index + 3] = '=';
        output_index += 4;
    }
    return output_index;
}
