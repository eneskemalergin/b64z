//! Strict RFC 4648 Base64 with caller-owned output buffers and an AVX2 fast path.
//!
//! `encode` and `decode` do not allocate. Callers must provide disjoint input and
//! output slices. The AVX2 path is compiled only for x86_64 targets with AVX2;
//! other targets use the scalar path until native implementations are added.

const std = @import("std");
const builtin = @import("builtin");

pub const Error = error{
    InputTooLarge,
    InvalidCharacter,
    InvalidPadding,
    NoSpaceLeft,
    OverlappingBuffers,
};

pub const Backend = enum {
    avx2,
    scalar,
};

const ALPHABET: [64]u8 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".*;
const PAD: u8 = '=';
const INVALID: u8 = 0xff;

// TODO: Add guarded AArch64 NEON and runtime x86 feature dispatch before
// publishing other targets. Future work also includes vectorized backward
// encodeInPlace and a target-specific SSSE3/SSE2 fallback.
const USE_AVX2 = switch (builtin.target.cpu.arch) {
    .x86_64 => builtin.cpu.has(.x86, .avx2),
    else => false,
};

pub const BACKEND: Backend = if (USE_AVX2) .avx2 else .scalar;

const DECODE_TABLE: [256]u8 = blk: {
    var table = [_]u8{INVALID} ** 256;
    for (ALPHABET, 0..) |character, index| table[character] = @intCast(index);
    break :blk table;
};

/// Returns the exact padded output length without allocating.
pub fn encodedSize(input_len: usize) Error!usize {
    if (input_len > std.math.maxInt(usize) - 2) return error.InputTooLarge;
    const groups = (input_len + 2) / 3;
    if (groups > std.math.maxInt(usize) / 4) return error.InputTooLarge;
    return groups * 4;
}

/// Returns the exact decoded length after checking the input length and final padding shape.
pub fn decodedSize(input: []const u8) Error!usize {
    if (input.len % 4 != 0) return error.InvalidPadding;

    var padding: usize = 0;
    if (input.len != 0 and input[input.len - 1] == PAD) padding = 1;
    if (input.len >= 2 and input[input.len - 2] == PAD) padding = 2;

    if (padding == 1) {
        if (input.len < 4 or input[input.len - 2] == PAD) return error.InvalidPadding;
    } else if (padding == 2) {
        if (input.len < 4 or input[input.len - 3] == PAD) return error.InvalidPadding;
    }

    const groups = input.len / 4;
    if (groups > (std.math.maxInt(usize) - padding) / 3) return error.InputTooLarge;
    return groups * 3 - padding;
}

/// Encodes strict standard Base64 into `output` and returns the number of bytes written.
/// The output slice must have the length returned by `encodedSize` or more and must not
/// overlap `input`.
pub fn encode(input: []const u8, output: []u8) Error!usize {
    if (slicesOverlap(input, output)) return error.OverlappingBuffers;
    const output_len = try encodedSize(input.len);
    if (output.len < output_len) return error.NoSpaceLeft;

    var input_index: usize = 0;
    var output_index: usize = 0;

    if (USE_AVX2) {
        while (input.len - input_index >= 32 + 24 * 3) {
            encodeAvx2Block(input[input_index..], output[output_index..]);
            encodeAvx2Block(input[input_index + 24 ..], output[output_index + 32 ..]);
            encodeAvx2Block(input[input_index + 48 ..], output[output_index + 64 ..]);
            encodeAvx2Block(input[input_index + 72 ..], output[output_index + 96 ..]);
            input_index += 24 * 4;
            output_index += 32 * 4;
        }
        while (input.len - input_index >= 32) {
            encodeAvx2Block(input[input_index..], output[output_index..]);
            input_index += 24;
            output_index += 32;
        }
    }

    while (input.len - input_index >= 3) {
        encodeTriple(input[input_index..][0..3], output[output_index..][0..4]);
        input_index += 3;
        output_index += 4;
    }

    const remaining = input.len - input_index;
    if (remaining == 1) {
        const first = input[input_index];
        output[output_index] = ALPHABET[first >> 2];
        output[output_index + 1] = ALPHABET[(first & 0x03) << 4];
        output[output_index + 2] = PAD;
        output[output_index + 3] = PAD;
    } else if (remaining == 2) {
        const first = input[input_index];
        const second = input[input_index + 1];
        output[output_index] = ALPHABET[first >> 2];
        output[output_index + 1] = ALPHABET[((first & 0x03) << 4) | (second >> 4)];
        output[output_index + 2] = ALPHABET[(second & 0x0f) << 2];
        output[output_index + 3] = PAD;
    }

    return output_len;
}

/// Decodes strict, canonical, unwrapped Base64 into `output` and returns the bytes written.
/// The output slice must have the length returned by `decodedSize` or more and must not
/// overlap `input`.
pub fn decode(input: []const u8, output: []u8) Error!usize {
    if (slicesOverlap(input, output)) return error.OverlappingBuffers;
    const output_len = try decodedSize(input);
    if (output.len < output_len) return error.NoSpaceLeft;

    var padding: usize = 0;
    if (input.len != 0 and input[input.len - 1] == PAD) padding = 1;
    if (input.len >= 2 and input[input.len - 2] == PAD) padding = 2;

    const plain_len = input.len - padding;
    var input_index: usize = 0;
    var output_index: usize = 0;

    if (USE_AVX2) {
        while (plain_len - input_index >= 32 * 4) {
            try decodeAvx2Block(input[input_index..], output[output_index..]);
            try decodeAvx2Block(input[input_index + 32 ..], output[output_index + 24 ..]);
            try decodeAvx2Block(input[input_index + 64 ..], output[output_index + 48 ..]);
            try decodeAvx2Block(input[input_index + 96 ..], output[output_index + 72 ..]);
            input_index += 32 * 4;
            output_index += 24 * 4;
        }
        while (plain_len - input_index >= 32) {
            try decodeAvx2Block(input[input_index..], output[output_index..]);
            input_index += 32;
            output_index += 24;
        }
    }

    const plain_groups_len = plain_len - (plain_len % 4);
    while (input_index < plain_groups_len) {
        try decodePlainGroup(input[input_index..][0..4], output[output_index..][0..3]);
        input_index += 4;
        output_index += 3;
    }

    if (padding != 0) {
        const group = input[input.len - 4 ..][0..4];
        output_index += try decodePaddedGroup(group, output[output_index..]);
    }

    return output_index;
}

/// Decodes Base64 from the start of `buffer` and compacts the decoded bytes into
/// the same buffer. The input is consumed before each overlapping write.
pub fn decodeInPlace(buffer: []u8) Error!usize {
    const output_len = try decodedSize(buffer);
    var padding: usize = 0;
    if (buffer.len != 0 and buffer[buffer.len - 1] == PAD) padding = 1;
    if (buffer.len >= 2 and buffer[buffer.len - 2] == PAD) padding = 2;

    const plain_len = buffer.len - padding;
    const plain_groups_len = plain_len - (plain_len % 4);
    var input_index: usize = 0;
    var output_index: usize = 0;
    while (input_index < plain_groups_len) {
        try decodePlainGroup(buffer[input_index..][0..4], buffer[output_index..][0..3]);
        input_index += 4;
        output_index += 3;
    }
    if (padding != 0) {
        output_index += try decodePaddedGroup(buffer[buffer.len - 4 ..], buffer[output_index..]);
    }
    std.debug.assert(output_index == output_len);
    return output_index;
}

/// Encodes the first `input_len` bytes of `buffer` into the same buffer.
/// `buffer.len` must include the exact encoded capacity. Groups are processed
/// from the end so output writes never destroy unread input.
pub fn encodeInPlace(buffer: []u8, input_len: usize) Error!usize {
    if (input_len > buffer.len) return error.NoSpaceLeft;
    const output_len = try encodedSize(input_len);
    if (buffer.len < output_len) return error.NoSpaceLeft;

    var input_end = input_len;
    var output_end = output_len;
    const remainder = input_len % 3;
    if (remainder != 0) {
        input_end -= remainder;
        output_end -= 4;
        encodeTail(buffer[input_end..input_len], buffer[output_end..][0..4]);
    }
    while (input_end != 0) {
        input_end -= 3;
        output_end -= 4;
        encodeTriple(buffer[input_end..][0..3], buffer[output_end..][0..4]);
    }
    std.debug.assert(output_end == 0);
    return output_len;
}

/// Stateful encoder for callers that receive input in arbitrary chunks.
/// `update` emits complete groups and `final` emits the padded tail. The input
/// and output slices passed to `update` must be disjoint. If `update` or
/// `updateByte` returns `error.NoSpaceLeft`, it leaves the encoder, input, and
/// output unchanged so the caller can retry with a larger output slice.
pub const Encoder = struct {
    carry: [3]u8 = undefined,
    carry_len: usize = 0,

    pub fn updateByte(self: *Encoder, byte: u8, output_slice: []u8) Error!usize {
        const required: usize = if (self.carry_len == 2 or self.carry_len == 3) 4 else 0;
        if (output_slice.len < required) return error.NoSpaceLeft;

        var output = output_slice;
        var output_index: usize = 0;
        if (self.carry_len == 3) {
            encodeTriple(&self.carry, output[0..4]);
            self.carry_len = 0;
            output_index = 4;
            output = output[4..];
        }
        self.carry[self.carry_len] = byte;
        self.carry_len += 1;
        if (self.carry_len != 3) return output_index;
        encodeTriple(&self.carry, output[0..4]);
        self.carry_len = 0;
        return output_index + 4;
    }

    pub fn update(self: *Encoder, input: []const u8, output: []u8) Error!usize {
        const required = try encoderUpdateOutputSize(self.carry_len, input.len);
        if (output.len < required) return error.NoSpaceLeft;

        var input_index: usize = 0;
        var output_index: usize = 0;
        if (self.carry_len != 0) {
            while (self.carry_len < 3 and input_index < input.len) {
                self.carry[self.carry_len] = input[input_index];
                self.carry_len += 1;
                input_index += 1;
            }
            if (self.carry_len == 3) {
                encodeTriple(&self.carry, output[0..4]);
                output_index = 4;
                self.carry_len = 0;
            }
        }

        const full_len = (input.len - input_index) / 3 * 3;
        if (full_len != 0) {
            const written = try encode(input[input_index..][0..full_len], output[output_index..]);
            output_index += written;
            input_index += full_len;
        }

        while (input_index < input.len) {
            self.carry[self.carry_len] = input[input_index];
            self.carry_len += 1;
            input_index += 1;
        }
        return output_index;
    }

    pub fn final(self: *Encoder, output: []u8) Error!usize {
        if (self.carry_len == 0) return 0;
        if (output.len < 4) return error.NoSpaceLeft;
        encodeTail(self.carry[0..self.carry_len], output[0..4]);
        self.carry_len = 0;
        return 4;
    }
};

/// Stateful strict decoder for callers that receive encoded input in arbitrary chunks.
/// Padding is held until `final`, so a padded group cannot be accepted before EOF.
/// The input and output slices passed to `update` must be disjoint. If `update`
/// or `updateByte` returns `error.NoSpaceLeft`, it leaves the decoder, input,
/// and output unchanged so the caller can retry with a larger output slice.
pub const Decoder = struct {
    carry: [4]u8 = undefined,
    carry_len: usize = 0,

    pub fn updateByte(self: *Decoder, byte: u8, output_slice: []u8) Error!usize {
        var preview = self.carry;
        var preview_len = self.carry_len;
        var required: usize = 0;
        if (preview_len == 4) {
            if (groupHasPadding(&preview)) return error.InvalidPadding;
            required = 3;
            preview_len = 0;
        }
        preview[preview_len] = byte;
        preview_len += 1;
        if (preview_len == 4 and !groupHasPadding(&preview)) required += 3;
        if (output_slice.len < required) return error.NoSpaceLeft;

        var output = output_slice;
        var output_index: usize = 0;
        if (self.carry_len == 4) {
            if (groupHasPadding(&self.carry)) return error.InvalidPadding;
            try decodePlainGroup(&self.carry, output[0..3]);
            self.carry_len = 0;
            output_index = 3;
            output = output[3..];
        }
        self.carry[self.carry_len] = byte;
        self.carry_len += 1;
        if (self.carry_len != 4) return output_index;
        if (groupHasPadding(&self.carry)) return output_index;
        try decodePlainGroup(&self.carry, output[0..3]);
        self.carry_len = 0;
        return output_index + 3;
    }

    pub fn update(self: *Decoder, input: []const u8, output: []u8) Error!usize {
        const required = try decoderUpdateOutputSize(self, input);
        if (output.len < required) return error.NoSpaceLeft;

        var input_index: usize = 0;
        var output_index: usize = 0;
        if (self.carry_len != 0) {
            while (self.carry_len < 4 and input_index < input.len) {
                self.carry[self.carry_len] = input[input_index];
                self.carry_len += 1;
                input_index += 1;
            }
            if (self.carry_len < 4) return 0;
            if (groupHasPadding(&self.carry)) {
                if (input_index != input.len) return error.InvalidPadding;
                return 0;
            }
            try decodePlainGroup(&self.carry, output[0..3]);
            output_index = 3;
            self.carry_len = 0;
        }

        const remaining = input.len - input_index;
        const full_len = remaining / 4 * 4;
        const full = input[input_index..][0..full_len];
        if (std.mem.indexOfScalar(u8, full, PAD)) |padding_index| {
            const padding_group_index = padding_index / 4 * 4;
            if (padding_group_index + 4 != full_len or full_len != remaining) {
                return error.InvalidPadding;
            }
            if (padding_group_index != 0) {
                output_index += try decode(
                    full[0..padding_group_index],
                    output[output_index..],
                );
            }
            @memcpy(&self.carry, full[padding_group_index..][0..4]);
            self.carry_len = 4;
            return output_index;
        }

        if (full_len != 0) {
            output_index += try decode(full, output[output_index..]);
            input_index += full_len;
        }

        while (input_index < input.len) {
            self.carry[self.carry_len] = input[input_index];
            self.carry_len += 1;
            input_index += 1;
        }
        return output_index;
    }

    pub fn final(self: *Decoder, output: []u8) Error!usize {
        if (self.carry_len == 0) return 0;
        if (self.carry_len != 4) return error.InvalidPadding;
        const required: usize = if (self.carry[2] == PAD) 1 else 2;
        if (output.len < required) return error.NoSpaceLeft;
        const written = try decodePaddedGroup(&self.carry, output);
        self.carry_len = 0;
        return written;
    }
};

fn encoderUpdateOutputSize(carry_len: usize, input_len: usize) Error!usize {
    if (input_len > std.math.maxInt(usize) - carry_len) return error.InputTooLarge;
    const complete_groups = (carry_len + input_len) / 3;
    if (complete_groups > std.math.maxInt(usize) / 4) return error.InputTooLarge;
    return complete_groups * 4;
}

fn decoderUpdateOutputSize(decoder: *const Decoder, input: []const u8) Error!usize {
    var input_index: usize = 0;
    var carry_len = decoder.carry_len;
    var output_len: usize = 0;
    var preview = decoder.carry;

    if (carry_len != 0) {
        while (carry_len < 4 and input_index < input.len) {
            preview[carry_len] = input[input_index];
            carry_len += 1;
            input_index += 1;
        }
        if (carry_len < 4) return 0;
        if (groupHasPadding(&preview)) {
            if (input_index != input.len) return error.InvalidPadding;
            return 0;
        }
        output_len = try addDecodedGroups(output_len, 1);
        carry_len = 0;
    }

    const remaining = input.len - input_index;
    const full_len = remaining / 4 * 4;
    const full = input[input_index..][0..full_len];
    if (std.mem.indexOfScalar(u8, full, PAD)) |padding_index| {
        const padding_group_index = padding_index / 4 * 4;
        if (padding_group_index + 4 != full_len or full_len != remaining) {
            return error.InvalidPadding;
        }
        return addDecodedGroups(output_len, padding_group_index / 4);
    }

    return addDecodedGroups(output_len, full_len / 4);
}

fn addDecodedGroups(output_len: usize, groups: usize) Error!usize {
    if (groups > std.math.maxInt(usize) / 3) return error.InputTooLarge;
    return std.math.add(usize, output_len, groups * 3) catch error.InputTooLarge;
}

fn slicesOverlap(a: []const u8, b: []const u8) bool {
    if (a.len == 0 or b.len == 0) return false;

    const a_start = @intFromPtr(a.ptr);
    const b_start = @intFromPtr(b.ptr);
    const a_end = std.math.add(usize, a_start, a.len) catch return true;
    const b_end = std.math.add(usize, b_start, b.len) catch return true;
    return a_start < b_end and b_start < a_end;
}

fn encodeTriple(input: []const u8, output: []u8) void {
    const first = input[0];
    const second = input[1];
    const third = input[2];
    output[0] = ALPHABET[first >> 2];
    output[1] = ALPHABET[((first & 0x03) << 4) | (second >> 4)];
    output[2] = ALPHABET[((second & 0x0f) << 2) | (third >> 6)];
    output[3] = ALPHABET[third & 0x3f];
}

fn encodeTail(input: []const u8, output: []u8) void {
    const first = input[0];
    output[0] = ALPHABET[first >> 2];
    if (input.len == 1) {
        output[1] = ALPHABET[(first & 0x03) << 4];
        output[2] = PAD;
        output[3] = PAD;
        return;
    }

    const second = input[1];
    output[1] = ALPHABET[((first & 0x03) << 4) | (second >> 4)];
    output[2] = ALPHABET[(second & 0x0f) << 2];
    output[3] = PAD;
}

fn groupHasPadding(group: []const u8) bool {
    return group[2] == PAD or group[3] == PAD;
}

fn decodePlainGroup(input: []const u8, output: []u8) Error!void {
    const first = DECODE_TABLE[input[0]];
    const second = DECODE_TABLE[input[1]];
    const third = DECODE_TABLE[input[2]];
    const fourth = DECODE_TABLE[input[3]];
    if (first == INVALID or second == INVALID or third == INVALID or fourth == INVALID) {
        if (input[0] == PAD or input[1] == PAD or input[2] == PAD or input[3] == PAD) {
            return error.InvalidPadding;
        }
        return error.InvalidCharacter;
    }

    const bits = (@as(u32, first) << 18) |
        (@as(u32, second) << 12) |
        (@as(u32, third) << 6) |
        fourth;
    output[0] = @truncate(bits >> 16);
    output[1] = @truncate(bits >> 8);
    output[2] = @truncate(bits);
}

fn decodePaddedGroup(input: []const u8, output: []u8) Error!usize {
    const first = DECODE_TABLE[input[0]];
    const second = DECODE_TABLE[input[1]];
    if (first == INVALID or second == INVALID) {
        if (input[0] == PAD or input[1] == PAD) return error.InvalidPadding;
        return error.InvalidCharacter;
    }

    if (input[2] == PAD) {
        if (input[3] != PAD or (second & 0x0f) != 0) return error.InvalidPadding;
        output[0] = (first << 2) | (second >> 4);
        return 1;
    }

    const third = DECODE_TABLE[input[2]];
    if (third == INVALID) {
        if (input[2] == PAD) return error.InvalidPadding;
        return error.InvalidCharacter;
    }
    if (input[3] != PAD) return error.InvalidPadding;
    if ((third & 0x03) != 0) return error.InvalidPadding;

    output[0] = (first << 2) | (second >> 4);
    output[1] = (second << 4) | (third >> 2);
    return 2;
}

const ByteVector = @Vector(32, u8);
const IndexVector = @Vector(32, i32);
const WordVector = @Vector(16, u16);
const DWordVector = @Vector(8, u32);

const ENCODE_RESHUFFLE_INDEX: IndexVector = .{
    1,  0,  2,  1,  4,  3,  5,  4,  7,  6,  8,  7,  10, 9,  11, 10,
    13, 12, 14, 13, 16, 15, 17, 16, 19, 18, 20, 19, 22, 21, 23, 22,
};

const ENCODE_T0_MASK: ByteVector = @bitCast(@as(DWordVector, @splat(0x0fc0fc00)));
const ENCODE_T1_MUL: WordVector = @bitCast(@as(DWordVector, @splat(0x04000040)));
const ENCODE_T1_SHIFT: WordVector = .{
    10, 6, 10, 6, 10, 6, 10, 6,
    10, 6, 10, 6, 10, 6, 10, 6,
};
const ENCODE_T2_MASK: ByteVector = @bitCast(@as(DWordVector, @splat(0x003f03f0)));
const ENCODE_T3_MUL_WORD: WordVector = @bitCast(@as(DWordVector, @splat(0x01000010)));
const ENCODE_T3_MUL: WordVector = .{
    0x0010, 0x0100, 0x0010, 0x0100, 0x0010, 0x0100, 0x0010, 0x0100,
    0x0010, 0x0100, 0x0010, 0x0100, 0x0010, 0x0100, 0x0010, 0x0100,
};

const DECODE_OUTPUT_INDEX: [24]i32 = .{
    2,  1,  0,  6,  5,  4,  10, 9,  8,  14, 13, 12,
    18, 17, 16, 22, 21, 20, 26, 25, 24, 30, 29, 28,
};

const DECODE_LUT_LO: ByteVector = .{
    0x15, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11,
    0x11, 0x11, 0x13, 0x1a, 0x1b, 0x1b, 0x1b, 0x1a,
    0x15, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11,
    0x11, 0x11, 0x13, 0x1a, 0x1b, 0x1b, 0x1b, 0x1a,
};
const DECODE_LUT_HI: ByteVector = .{
    0x10, 0x10, 0x01, 0x02, 0x04, 0x08, 0x04, 0x08,
    0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10,
    0x10, 0x10, 0x01, 0x02, 0x04, 0x08, 0x04, 0x08,
    0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10,
};
const DECODE_LUT_ROLL: ByteVector = .{
    0, 16, 19, 4, 0xbf, 0xbf, 0xb9, 0xb9,
    0, 0,  0,  0, 0,    0,    0,    0,
    0, 16, 19, 4, 0xbf, 0xbf, 0xb9, 0xb9,
    0, 0,  0,  0, 0,    0,    0,    0,
};
const DECODE_MASK_2F: ByteVector = @splat(0x2f);
const DECODE_MADDUBSW: ByteVector = .{
    0x40, 0x01, 0x40, 0x01, 0x40, 0x01, 0x40, 0x01,
    0x40, 0x01, 0x40, 0x01, 0x40, 0x01, 0x40, 0x01,
    0x40, 0x01, 0x40, 0x01, 0x40, 0x01, 0x40, 0x01,
    0x40, 0x01, 0x40, 0x01, 0x40, 0x01, 0x40, 0x01,
};
const DECODE_MADDWD: DWordVector = @splat(0x00011000);
const DECODE_PACK_INDEX: ByteVector = .{
    2, 1, 0, 6, 5, 4, 10, 9, 8, 14, 13, 12, 0xff, 0xff, 0xff, 0xff,
    2, 1, 0, 6, 5, 4, 10, 9, 8, 14, 13, 12, 0xff, 0xff, 0xff, 0xff,
};
const DECODE_PACKED_INDEX: [24]i32 = .{
    0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10, 11,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
};

fn encodeAvx2Block(input: []const u8, output: []u8) void {
    const bytes: ByteVector = input[0..32].*;
    const shuffled = @shuffle(u8, bytes, undefined, ENCODE_RESHUFFLE_INDEX);
    const values = if (comptime USE_AVX2)
        encodeReshuffleAvx2(shuffled)
    else
        encodeReshuffleScalar(shuffled);

    const translated = if (comptime USE_AVX2)
        encodeTranslateAvx2(values)
    else
        encodeTranslate(values);
    @memcpy(output[0..32], std.mem.asBytes(&translated));
}

fn encodeReshuffleScalar(shuffled: ByteVector) ByteVector {
    const t0_words: WordVector = @bitCast(shuffled & ENCODE_T0_MASK);
    const t1_words = t0_words >> ENCODE_T1_SHIFT;
    const t2_words: WordVector = @bitCast(shuffled & ENCODE_T2_MASK);
    const t3_words = t2_words *% ENCODE_T3_MUL;
    return @bitCast(t1_words | t3_words);
}

fn encodeReshuffleAvx2(shuffled: ByteVector) ByteVector {
    var t0: WordVector = undefined;
    var t1: WordVector = undefined;
    var t2: WordVector = undefined;
    var t3: WordVector = undefined;
    var values: ByteVector = undefined;
    asm volatile (
        \\vpand %[mask0], %[shuffled], %[t0]
        \\vpand %[mask2], %[shuffled], %[t2]
        \\vpmulhuw %[mul1], %[t0], %[t1]
        \\vpmullw %[mul3], %[t2], %[t3]
        \\vpor %[t3], %[t1], %[values]
        : [t0] "=&x" (t0),
          [t1] "=&x" (t1),
          [t2] "=&x" (t2),
          [t3] "=&x" (t3),
          [values] "=&x" (values),
        : [shuffled] "x" (shuffled),
          [mask0] "x" (ENCODE_T0_MASK),
          [mask2] "x" (ENCODE_T2_MASK),
          [mul1] "x" (ENCODE_T1_MUL),
          [mul3] "x" (ENCODE_T3_MUL_WORD),
    );
    return values;
}

fn encodeTranslate(values: ByteVector) ByteVector {
    const twenty_five: ByteVector = @splat(25);
    const fifty_one: ByteVector = @splat(51);
    const sixty_one: ByteVector = @splat(61);
    const sixty_two: ByteVector = @splat(62);

    var result = values +% @as(ByteVector, @splat(65));
    result = @select(u8, values > twenty_five, values +% @as(ByteVector, @splat(71)), result);
    result = @select(u8, values > fifty_one, values -% @as(ByteVector, @splat(4)), result);
    result = @select(u8, values > sixty_one, values -% @as(ByteVector, @splat(16)), result);
    result = @select(u8, values == sixty_two, values -% @as(ByteVector, @splat(19)), result);
    return result;
}

fn encodeTranslateAvx2(values: ByteVector) ByteVector {
    const lut: ByteVector = .{
        65,   71,   0xfc, 0xfc, 0xfc, 0xfc, 0xfc, 0xfc,
        0xfc, 0xfc, 0xfc, 0xfc, 0xed, 0xf0, 0,    0,
        65,   71,   0xfc, 0xfc, 0xfc, 0xfc, 0xfc, 0xfc,
        0xfc, 0xfc, 0xfc, 0xfc, 0xed, 0xf0, 0,    0,
    };
    const n51: ByteVector = @splat(51);
    const n25: ByteVector = @splat(25);

    var indices: ByteVector = undefined;
    var mask: ByteVector = undefined;
    var offsets: ByteVector = undefined;
    var result: ByteVector = undefined;
    asm volatile (
        \\vpsubusb %[n51], %[values], %[indices]
        \\vpcmpgtb %[n25], %[values], %[mask]
        \\vpsubb %[mask], %[indices], %[indices]
        \\vpshufb %[indices], %[lut], %[offsets]
        \\vpaddb %[values], %[offsets], %[result]
        : [indices] "=&x" (indices),
          [mask] "=&x" (mask),
          [offsets] "=&x" (offsets),
          [result] "=&x" (result),
        : [values] "x" (values),
          [n51] "x" (n51),
          [n25] "x" (n25),
          [lut] "x" (lut),
    );
    return result;
}

fn decodeAvx2Block(input: []const u8, output: []u8) Error!void {
    const chars: ByteVector = input[0..32].*;
    var hi_nibbles: ByteVector = undefined;
    var lo_nibbles: ByteVector = undefined;
    var hi: ByteVector = undefined;
    var lo: ByteVector = undefined;
    asm volatile (
        \\vpsrld $4, %[chars], %[hi_nibbles]
        \\vpand %[mask_2f], %[hi_nibbles], %[hi_nibbles]
        \\vpand %[mask_2f], %[chars], %[lo_nibbles]
        \\vpshufb %[hi_nibbles], %[lut_hi], %[hi]
        \\vpshufb %[lo_nibbles], %[lut_lo], %[lo]
        \\vpand %[hi], %[lo], %[lo]
        : [hi_nibbles] "=&x" (hi_nibbles),
          [lo_nibbles] "=&x" (lo_nibbles),
          [hi] "=&x" (hi),
          [lo] "=&x" (lo),
        : [chars] "x" (chars),
          [mask_2f] "x" (DECODE_MASK_2F),
          [lut_hi] "x" (DECODE_LUT_HI),
          [lut_lo] "x" (DECODE_LUT_LO),
    );
    if (@reduce(.Or, lo) != 0) {
        if (@reduce(.Or, chars == @as(ByteVector, @splat(PAD)))) return error.InvalidPadding;
        return error.InvalidCharacter;
    }

    var roll_index: ByteVector = undefined;
    var roll: ByteVector = undefined;
    var translated: ByteVector = undefined;
    var merged: WordVector = undefined;
    var packed_words: DWordVector = undefined;
    var packed_bytes: ByteVector = undefined;
    asm volatile (
        \\vpcmpeqb %[mask_2f], %[chars], %[roll_index]
        \\vpaddb %[roll_index], %[hi_nibbles], %[roll_index]
        \\vpshufb %[roll_index], %[lut_roll], %[roll]
        \\vpaddb %[roll], %[chars], %[translated]
        \\vpmaddubsw %[maddubsw], %[translated], %[merged]
        \\vpmaddwd %[maddwd], %[merged], %[packed_words]
        \\vpshufb %[pack_index], %[packed_words], %[packed_bytes]
        : [roll_index] "=&x" (roll_index),
          [roll] "=&x" (roll),
          [translated] "=&x" (translated),
          [merged] "=&x" (merged),
          [packed_words] "=&x" (packed_words),
          [packed_bytes] "=&x" (packed_bytes),
        : [chars] "x" (chars),
          [hi_nibbles] "x" (hi_nibbles),
          [mask_2f] "x" (DECODE_MASK_2F),
          [lut_roll] "x" (DECODE_LUT_ROLL),
          [maddubsw] "x" (DECODE_MADDUBSW),
          [maddwd] "x" (DECODE_MADDWD),
          [pack_index] "x" (DECODE_PACK_INDEX),
    );

    const packed_output: @Vector(24, u8) = @shuffle(
        u8,
        packed_bytes,
        undefined,
        @as(@Vector(24, i32), DECODE_PACKED_INDEX),
    );
    @memcpy(output[0..24], std.mem.asBytes(&packed_output)[0..24]);
}

test "[property] - [simd kernel]: matches scalar blocks" {
    if (!USE_AVX2) return;

    var input: [256]u8 = undefined;
    for (&input, 0..) |*byte, index| byte.* = @truncate(index * 37 + 11);

    var scalar_encoded: [512]u8 = undefined;
    var vector_encoded: [512]u8 = undefined;
    var vector_decoded: [256]u8 = undefined;

    var input_index: usize = 0;
    var encoded_index: usize = 0;
    while (input.len - input_index >= 32) {
        encodeAvx2Block(input[input_index..], vector_encoded[encoded_index..]);
        var scalar_index: usize = 0;
        while (scalar_index < 24) : (scalar_index += 3) {
            encodeTriple(input[input_index + scalar_index ..][0..3], scalar_encoded[encoded_index + scalar_index / 3 * 4 ..]);
        }
        try std.testing.expectEqualSlices(u8, scalar_encoded[encoded_index .. encoded_index + 32], vector_encoded[encoded_index .. encoded_index + 32]);
        input_index += 24;
        encoded_index += 32;
    }

    var decode_index: usize = 0;
    while (decode_index < encoded_index) : (decode_index += 32) {
        const decoded_offset = decode_index / 32 * 24;
        try decodeAvx2Block(vector_encoded[decode_index..], vector_decoded[decoded_offset..]);
        for (0..24) |index| {
            try std.testing.expectEqual(
                input[decoded_offset + index],
                vector_decoded[decoded_offset + index],
            );
        }
    }
}
