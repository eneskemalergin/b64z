//! Strict padded RFC 4648 Base64 with caller-owned buffers.
//!
//! The codec never allocates. `encode`, `decode`, and the stateful `update` calls require
//! disjoint input and output slices; `encodeInPlace` and `decodeInPlace` convert within one
//! buffer. Output capacity is checked before any write. Decode errors follow input order at
//! every entry point: the first defective group decides the error, and a missing or incomplete
//! final group is reported after the groups before it.
//!
//! x86-64 builds with AVX2 use vector kernels; other builds use the scalar path. Both produce
//! identical bytes and errors.
//!
//! The AVX2 kernels include Aklomp Base64 code under BSD-2-Clause. See
//! `THIRD_PARTY_NOTICES.md` in the repository root for attribution and license terms.

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

pub const BACKEND: Backend = if (USE_AVX2) .avx2 else .scalar;

/// Returns the exact padded output length without allocating.
pub fn encodedSize(input_len: usize) Error!usize {
    if (input_len > std.math.maxInt(usize) - 2) return error.InputTooLarge;
    const groups = (input_len + 2) / 3;
    if (groups > std.math.maxInt(usize) / 4) return error.InputTooLarge;
    return groups * 4;
}

/// Returns the exact decoded length after checking the input length and final padding shape.
/// It does not validate alphabet bytes; `decode` performs that check.
pub fn decodedSize(input: []const u8) Error!usize {
    if (input.len % 4 != 0) return error.InvalidPadding;
    const layout: Layout = .of(input);
    if (layout.padded) {
        const last = input[layout.plain_len..][0..4];
        if (last[0] == PAD or last[1] == PAD or last[3] != PAD) return error.InvalidPadding;
    }
    return layout.decoded_len;
}

/// Encodes strict standard Base64 into `output` and returns the number of bytes written.
/// `output` must hold `encodedSize(input.len)` bytes, or the call returns `error.NoSpaceLeft`.
/// It must not overlap `input`, or the call returns `error.OverlappingBuffers`.
pub fn encode(input: []const u8, output: []u8) Error!usize {
    if (slicesOverlap(input, output)) return error.OverlappingBuffers;
    const output_len = try encodedSize(input.len);
    if (output.len < output_len) return error.NoSpaceLeft;
    encodeForward(input, output);
    return output_len;
}

/// Decodes strict, canonical, unwrapped Base64 into `output` and returns the bytes written.
/// `output` must hold `decodedSize(input)` bytes, or the call returns `error.NoSpaceLeft`.
/// It must not overlap `input`, or the call returns `error.OverlappingBuffers`.
pub fn decode(input: []const u8, output: []u8) Error!usize {
    if (slicesOverlap(input, output)) return error.OverlappingBuffers;
    const layout: Layout = .of(input);
    if (output.len < layout.decoded_len) return error.NoSpaceLeft;
    return decodeLayout(input, output, layout);
}

/// Encodes the first `input_len` bytes of `buffer` into the same buffer and returns the
/// encoded length. `buffer.len` must include `encodedSize(input_len)`, or the call returns
/// `error.NoSpaceLeft`. Groups run from the end so every write lands on bytes already read.
pub fn encodeInPlace(buffer: []u8, input_len: usize) Error!usize {
    if (input_len > buffer.len) return error.NoSpaceLeft;
    const output_len = try encodedSize(input_len);
    if (buffer.len < output_len) return error.NoSpaceLeft;

    var input_end = input_len - input_len % 3;
    var output_end = input_end / 3 * 4;
    if (input_end != input_len) {
        encodeTail(buffer[input_end..input_len], buffer[output_end..][0..4]);
    }
    if (USE_AVX2) {
        while (input_end >= 28 + 24 * 3) {
            inline for (1..5) |block| {
                encodeBlock(
                    buffer[input_end - 24 * block - 4 ..][0..32],
                    buffer[output_end - 32 * block ..][0..32],
                );
            }
            input_end -= 24 * 4;
            output_end -= 32 * 4;
        }
        while (input_end >= 28) {
            encodeBlock(buffer[input_end - 28 ..][0..32], buffer[output_end - 32 ..][0..32]);
            input_end -= 24;
            output_end -= 32;
        }
    }
    while (input_end != 0) {
        input_end -= 3;
        output_end -= 4;
        encodeTriple(buffer[input_end..][0..3], buffer[output_end..][0..4]);
    }
    return output_len;
}

/// Decodes all of `buffer` into its own start and returns the decoded length. Each group is
/// read before its output is written. After an error, the buffer contents are unspecified.
pub fn decodeInPlace(buffer: []u8) Error!usize {
    return decodeLayout(buffer, buffer, .of(buffer));
}

/// Stateful encoder for input that arrives in arbitrary chunks. `update` writes complete groups
/// and `final` writes the padded tail. The slices passed to `update` must be disjoint, or it
/// returns `error.OverlappingBuffers`. After that error or `error.NoSpaceLeft`, the encoder and
/// the output are unchanged, so the caller can retry with a corrected output slice.
pub const Encoder = struct {
    carry: [3]u8 = undefined,
    carry_len: usize = 0,

    pub fn updateByte(self: *Encoder, byte: u8, output: []u8) Error!usize {
        return self.update(&.{byte}, output);
    }

    pub fn update(self: *Encoder, input: []const u8, output: []u8) Error!usize {
        if (slicesOverlap(input, output)) return error.OverlappingBuffers;
        const total = std.math.add(usize, self.carry_len, input.len) catch
            return error.InputTooLarge;
        const required = std.math.mul(usize, total / 3, 4) catch return error.InputTooLarge;
        if (output.len < required) return error.NoSpaceLeft;

        var input_index: usize = 0;
        var output_index: usize = 0;
        if (self.carry_len != 0) {
            input_index = @min(3 - self.carry_len, input.len);
            @memcpy(self.carry[self.carry_len..][0..input_index], input[0..input_index]);
            self.carry_len += input_index;
            if (self.carry_len < 3) return 0;
            encodeTriple(&self.carry, output[0..4]);
            output_index = 4;
        }

        const tail = input[input.len - (input.len - input_index) % 3 ..];
        const body = input[input_index .. input.len - tail.len];
        encodeForward(body, output[output_index..]);
        @memcpy(self.carry[0..tail.len], tail);
        self.carry_len = tail.len;
        return output_index + body.len / 3 * 4;
    }

    pub fn final(self: *Encoder, output: []u8) Error!usize {
        if (self.carry_len == 0) return 0;
        if (output.len < 4) return error.NoSpaceLeft;
        encodeTail(self.carry[0..self.carry_len], output[0..4]);
        self.carry_len = 0;
        return 4;
    }
};

/// Stateful strict decoder for input that arrives in arbitrary chunks. A group with padding
/// stays in the decoder until `final` checks and writes it, so padding is accepted only at the
/// end. The slices passed to `update` must be disjoint, or it returns
/// `error.OverlappingBuffers`. After that error or `error.NoSpaceLeft`, the decoder and the
/// output are unchanged, so the caller can retry with a corrected output slice.
pub const Decoder = struct {
    carry: [4]u8 = undefined,
    carry_len: usize = 0,

    pub fn updateByte(self: *Decoder, byte: u8, output: []u8) Error!usize {
        return self.update(&.{byte}, output);
    }

    pub fn update(self: *Decoder, input: []const u8, output: []u8) Error!usize {
        if (slicesOverlap(input, output)) return error.OverlappingBuffers;
        if (self.carry_len == 4) {
            if (input.len != 0) return error.InvalidPadding;
            return 0;
        }

        var group = self.carry;
        const fill: usize = if (self.carry_len == 0) 0 else @min(4 - self.carry_len, input.len);
        @memcpy(group[self.carry_len..][0..fill], input[0..fill]);
        const group_len = self.carry_len + fill;
        if (group_len != 0 and group_len < 4) {
            self.carry = group;
            self.carry_len = group_len;
            return 0;
        }

        // Only the last complete group of this call can be the padded final group.
        const rest = input[fill..];
        const groups_end = rest.len - rest.len % 4;
        const hold_last = groups_end == rest.len and groups_end != 0 and
            groupHasPadding(rest[groups_end - 4 ..][0..4]);
        const plain_end = groups_end - @as(usize, if (hold_last) 4 else 0);
        const carry_plain = group_len == 4 and !groupHasPadding(&group);
        if (output.len < (plain_end / 4 + @intFromBool(carry_plain)) * 3) {
            return error.NoSpaceLeft;
        }

        var output_index: usize = 0;
        if (group_len == 4) {
            if (!carry_plain) {
                if (rest.len != 0) return error.InvalidPadding;
                self.carry = group;
                self.carry_len = 4;
                return 0;
            }
            try decodePlainGroup(&group, output[0..3]);
            output_index = 3;
        }
        output_index += try decodeGroups(rest[0..plain_end], output[output_index..]);
        const kept = rest[plain_end..];
        @memcpy(self.carry[0..kept.len], kept);
        self.carry_len = kept.len;
        return output_index;
    }

    pub fn final(self: *Decoder, output: []u8) Error!usize {
        if (self.carry_len == 0) return 0;
        if (self.carry_len != 4) return error.InvalidPadding;
        if (output.len < paddedGroupLen(&self.carry)) return error.NoSpaceLeft;
        const written = try decodePaddedGroup(&self.carry, output);
        self.carry_len = 0;
        return written;
    }
};

const USE_AVX2 = switch (builtin.target.cpu.arch) {
    .x86_64 => builtin.cpu.has(.x86, .avx2),
    else => false,
};

const ALPHABET: [64]u8 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".*;
const PAD: u8 = '=';
const INVALID: u8 = 0xff;

const DECODE_TABLE: [256]u8 = blk: {
    var table = [_]u8{INVALID} ** 256;
    for (ALPHABET, 0..) |character, index| table[character] = @intCast(index);
    break :blk table;
};

/// Splits encoded input into complete groups decoded as plain data and an optional final group
/// with padding. The layout does not validate bytes.
const Layout = struct {
    plain_len: usize,
    padded: bool,
    decoded_len: usize,

    fn of(input: []const u8) Layout {
        const groups_len = input.len - input.len % 4;
        const padded = groups_len == input.len and groups_len != 0 and
            groupHasPadding(input[groups_len - 4 ..][0..4]);
        const plain_len = groups_len - @as(usize, if (padded) 4 else 0);
        const padded_len = if (padded) paddedGroupLen(input[plain_len..][0..4]) else 0;
        return .{
            .plain_len = plain_len,
            .padded = padded,
            .decoded_len = plain_len / 4 * 3 + padded_len,
        };
    }
};

fn decodeLayout(input: []const u8, output: []u8, layout: Layout) Error!usize {
    var output_len = try decodeGroups(input[0..layout.plain_len], output);
    if (layout.padded) {
        output_len += try decodePaddedGroup(input[layout.plain_len..][0..4], output[output_len..]);
    }
    if (input.len % 4 != 0) return error.InvalidPadding;
    return output_len;
}

/// Encodes `input` into the first `encodedSize(input.len)` bytes of `output`.
fn encodeForward(input: []const u8, output: []u8) void {
    var input_index: usize = 0;
    var output_index: usize = 0;
    // Vector blocks load from four bytes before their group, so the first block runs scalar.
    if (USE_AVX2 and input.len >= 24 + 28) {
        while (input_index < 24) {
            encodeTriple(input[input_index..][0..3], output[output_index..][0..4]);
            input_index += 3;
            output_index += 4;
        }
        while (input.len - input_index >= 28 + 24 * 3) {
            inline for (0..4) |block| {
                encodeBlock(
                    input[input_index + 24 * block - 4 ..][0..32],
                    output[output_index + 32 * block ..][0..32],
                );
            }
            input_index += 24 * 4;
            output_index += 32 * 4;
        }
        while (input.len - input_index >= 28) {
            encodeBlock(input[input_index - 4 ..][0..32], output[output_index..][0..32]);
            input_index += 24;
            output_index += 32;
        }
    }
    while (input.len - input_index >= 3) {
        encodeTriple(input[input_index..][0..3], output[output_index..][0..4]);
        input_index += 3;
        output_index += 4;
    }
    if (input_index != input.len) encodeTail(input[input_index..], output[output_index..][0..4]);
}

/// Decodes complete groups that may not contain padding. In-place callers pass one buffer as
/// both slices: each block is read before its output is written, and each output ends before
/// the next unread group.
fn decodeGroups(input: []const u8, output: []u8) Error!usize {
    var input_index: usize = 0;
    var output_index: usize = 0;
    if (USE_AVX2) {
        // A block stores 32 bytes for 24 decoded bytes, so each store needs 8 bytes of slack.
        // Credit: the full-width store with slack comes from the AVX2 decoder in Aklomp's base64
        // library (https://github.com/aklomp/base64).
        while (input.len - input_index >= 32 * 4 and output.len - output_index >= 24 * 3 + 32) {
            inline for (0..4) |block| {
                try decodeBlock(
                    input[input_index + 32 * block ..][0..32],
                    output[output_index + 24 * block ..][0..32],
                );
            }
            input_index += 32 * 4;
            output_index += 24 * 4;
        }
        while (input.len - input_index >= 32 and output.len - output_index >= 32) {
            try decodeBlock(input[input_index..][0..32], output[output_index..][0..32]);
            input_index += 32;
            output_index += 24;
        }
    }
    while (input_index < input.len) {
        try decodePlainGroup(input[input_index..][0..4], output[output_index..][0..3]);
        input_index += 4;
        output_index += 3;
    }
    return output_index;
}

fn slicesOverlap(a: []const u8, b: []const u8) bool {
    if (a.len == 0 or b.len == 0) return false;

    const a_start = @intFromPtr(a.ptr);
    const b_start = @intFromPtr(b.ptr);
    const a_end = std.math.add(usize, a_start, a.len) catch return true;
    const b_end = std.math.add(usize, b_start, b.len) catch return true;
    return a_start < b_end and b_start < a_end;
}

fn encodeTriple(input: *const [3]u8, output: *[4]u8) void {
    const first = input[0];
    const second = input[1];
    const third = input[2];
    output[0] = ALPHABET[first >> 2];
    output[1] = ALPHABET[((first & 0x03) << 4) | (second >> 4)];
    output[2] = ALPHABET[((second & 0x0f) << 2) | (third >> 6)];
    output[3] = ALPHABET[third & 0x3f];
}

/// Encodes a one- or two-byte tail. Both input bytes are read before any write because
/// `encodeInPlace` can place the output one byte after the tail's start.
fn encodeTail(input: []const u8, output: *[4]u8) void {
    const first = input[0];
    const second: u8 = if (input.len == 2) input[1] else 0;
    output[0] = ALPHABET[first >> 2];
    output[1] = ALPHABET[((first & 0x03) << 4) | (second >> 4)];
    output[2] = if (input.len == 2) ALPHABET[(second & 0x0f) << 2] else PAD;
    output[3] = PAD;
}

fn groupHasPadding(group: *const [4]u8) bool {
    return group[2] == PAD or group[3] == PAD;
}

fn paddedGroupLen(group: *const [4]u8) usize {
    return if (group[2] == PAD) 1 else 2;
}

fn decodePlainGroup(input: *const [4]u8, output: *[3]u8) Error!void {
    const first = DECODE_TABLE[input[0]];
    const second = DECODE_TABLE[input[1]];
    const third = DECODE_TABLE[input[2]];
    const fourth = DECODE_TABLE[input[3]];
    if (first == INVALID or second == INVALID or third == INVALID or fourth == INVALID) {
        if (std.mem.indexOfScalar(u8, input, PAD) != null) return error.InvalidPadding;
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

fn decodePaddedGroup(input: *const [4]u8, output: []u8) Error!usize {
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
    if (third == INVALID) return error.InvalidCharacter;
    if (input[3] != PAD or (third & 0x03) != 0) return error.InvalidPadding;
    output[0] = (first << 2) | (second >> 4);
    output[1] = (second << 4) | (third >> 2);
    return 2;
}

// --- AVX2 kernels ---

const ByteVector = @Vector(32, u8);
const IndexVector = @Vector(32, i32);
const WordVector = @Vector(16, u16);
const DWordVector = @Vector(8, u32);

const ENCODE_SHUFFLE: ByteVector = .{
    5, 4, 6, 5, 8, 7, 9, 8, 11, 10, 12, 11, 14, 13, 15, 14,
    1, 0, 2, 1, 4, 3, 5, 4, 7,  6,  8,  7,  10, 9,  11, 10,
};
const ENCODE_MASK_HIGH: ByteVector = @bitCast(@as(DWordVector, @splat(0x0fc0fc00)));
const ENCODE_MUL_HIGH: WordVector = @bitCast(@as(DWordVector, @splat(0x04000040)));
const ENCODE_MASK_LOW: ByteVector = @bitCast(@as(DWordVector, @splat(0x003f03f0)));
const ENCODE_MUL_LOW: WordVector = @bitCast(@as(DWordVector, @splat(0x01000010)));
const ENCODE_OFFSETS: ByteVector = .{
    65,   71,   0xfc, 0xfc, 0xfc, 0xfc, 0xfc, 0xfc,
    0xfc, 0xfc, 0xfc, 0xfc, 0xed, 0xf0, 0,    0,
    65,   71,   0xfc, 0xfc, 0xfc, 0xfc, 0xfc, 0xfc,
    0xfc, 0xfc, 0xfc, 0xfc, 0xed, 0xf0, 0,    0,
};
const ENCODE_LOWER_LAST: ByteVector = @splat(51);
const ENCODE_UPPER_LAST: ByteVector = @splat(25);

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
const DECODE_MADDUBSW: ByteVector = @bitCast(@as(DWordVector, @splat(0x01400140)));
const DECODE_MADDWD: DWordVector = @splat(0x00011000);
const DECODE_PACK_LANES: ByteVector = .{
    2, 1, 0, 6, 5, 4, 10, 9, 8, 14, 13, 12, 0xff, 0xff, 0xff, 0xff,
    2, 1, 0, 6, 5, 4, 10, 9, 8, 14, 13, 12, 0xff, 0xff, 0xff, 0xff,
};
const DECODE_PACK_OUTPUT: IndexVector = .{
    0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10, 11,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
    12, 13, 14, 15, 28, 29, 30, 31,
};

// Credit: the four-byte-early 32-byte load, the in-lane shuffle, and the instruction order of
// this kernel come from the AVX2 encoder in Aklomp's base64 library
// (https://github.com/aklomp/base64).
/// Encodes the 24 bytes at `input[4..28]` into `output`. Loading from four bytes before the
/// group keeps each lane's 12 input bytes in that lane. The shuffle stays in assembly because
/// LLVM otherwise narrows the 32-byte load into a slower cross-lane sequence.
inline fn encodeBlock(input: *const [32]u8, output: *[32]u8) void {
    const bytes: ByteVector = input.*;
    var result: ByteVector = undefined;
    var values: ByteVector = undefined;
    var scratch: ByteVector = undefined;
    asm (
        \\vpshufb %[shuffle], %[bytes], %[values]
        \\vpand %[values], %[mask_high], %[scratch]
        \\vpand %[values], %[mask_low], %[values]
        \\vpmulhuw %[scratch], %[mul_high], %[scratch]
        \\vpmullw %[values], %[mul_low], %[values]
        \\vpor %[values], %[scratch], %[values]
        \\vpsubusb %[lower_last], %[values], %[result]
        \\vpcmpgtb %[upper_last], %[values], %[scratch]
        \\vpsubb %[scratch], %[result], %[result]
        \\vpshufb %[result], %[offsets], %[scratch]
        \\vpaddb %[values], %[scratch], %[result]
        : [result] "=&x" (result),
          [values] "=&x" (values),
          [scratch] "=&x" (scratch),
        : [bytes] "x" (bytes),
          [shuffle] "x" (ENCODE_SHUFFLE),
          [mask_high] "x" (ENCODE_MASK_HIGH),
          [mask_low] "x" (ENCODE_MASK_LOW),
          [mul_high] "x" (ENCODE_MUL_HIGH),
          [mul_low] "x" (ENCODE_MUL_LOW),
          [lower_last] "x" (ENCODE_LOWER_LAST),
          [upper_last] "x" (ENCODE_UPPER_LAST),
          [offsets] "x" (ENCODE_OFFSETS),
    );
    output.* = result;
}

/// Decodes one 32-byte block into the first 24 bytes of `output` and overwrites the remaining
/// 8. A block that fails the vector check is decoded again by the scalar groups, which report
/// the first defective group.
inline fn decodeBlock(input: *const [32]u8, output: *[32]u8) Error!void {
    const chars: ByteVector = input.*;
    const shifted: ByteVector = @bitCast(@as(DWordVector, @bitCast(chars)) >> @splat(4));
    const hi_nibbles = shifted & DECODE_MASK_2F;
    const hi = pshufb(DECODE_LUT_HI, hi_nibbles);
    const lo = pshufb(DECODE_LUT_LO, chars & DECODE_MASK_2F);
    if (@reduce(.Or, hi & lo) != 0) {
        @branchHint(.cold);
        for (0..8) |group| {
            try decodePlainGroup(input[group * 4 ..][0..4], output[group * 3 ..][0..3]);
        }
        return;
    }

    const all_ones: ByteVector = @splat(0xff);
    const zeros: ByteVector = @splat(0);
    const slash = @select(u8, chars == DECODE_MASK_2F, all_ones, zeros);
    const translated = chars +% pshufb(DECODE_LUT_ROLL, slash +% hi_nibbles);
    var packed_lanes: ByteVector = undefined;
    asm (
        \\vpmaddubsw %[maddubsw], %[translated], %[packed_lanes]
        \\vpmaddwd %[maddwd], %[packed_lanes], %[packed_lanes]
        \\vpshufb %[pack], %[packed_lanes], %[packed_lanes]
        : [packed_lanes] "=&x" (packed_lanes),
        : [translated] "x" (translated),
          [maddubsw] "x" (DECODE_MADDUBSW),
          [maddwd] "x" (DECODE_MADDWD),
          [pack] "x" (DECODE_PACK_LANES),
    );
    output.* = @shuffle(u8, packed_lanes, undefined, DECODE_PACK_OUTPUT);
}

inline fn pshufb(table: ByteVector, indices: ByteVector) ByteVector {
    var result: ByteVector = undefined;
    asm ("vpshufb %[indices], %[table], %[result]"
        : [result] "=x" (result),
        : [indices] "x" (indices),
          [table] "x" (table),
    );
    return result;
}

test "[property] - [simd kernel]: matches scalar groups on generated blocks" {
    if (!USE_AVX2) return error.SkipZigTest;

    var input: [32]u8 = undefined;
    var vector_output: [32]u8 = undefined;
    var scalar_output: [32]u8 = undefined;
    for (0..64) |seed| {
        for (&input, 0..) |*byte, index| byte.* = @truncate(index * 37 + seed * 101 + 11);
        encodeBlock(&input, &vector_output);
        for (0..8) |group| {
            encodeTriple(input[4 + group * 3 ..][0..3], scalar_output[group * 4 ..][0..4]);
        }
        try std.testing.expectEqualSlices(u8, &scalar_output, &vector_output);

        var decoded: [32]u8 = undefined;
        try decodeBlock(&vector_output, &decoded);
        try std.testing.expectEqualSlices(u8, input[4..28], decoded[0..24]);
    }
}

test "[property] - [simd kernel]: classifies every byte at every lane" {
    if (!USE_AVX2) return error.SkipZigTest;

    var block = [_]u8{'A'} ** 32;
    var output: [32]u8 = undefined;
    for (0..32) |lane| {
        for (0..256) |value| {
            block[lane] = @intCast(value);
            const result = decodeBlock(&block, &output);
            if (DECODE_TABLE[value] != INVALID) {
                try result;
            } else if (value == PAD) {
                try std.testing.expectError(error.InvalidPadding, result);
            } else {
                try std.testing.expectError(error.InvalidCharacter, result);
            }
        }
        block[lane] = 'A';
    }
}
