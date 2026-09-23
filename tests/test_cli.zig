//! Command-line tests for `custom-base64`: exit status, standard output, and standard error for
//! each mode and argument form.
//!
//! Each test runs the executable that `build.zig` builds, with inputs written to a test-owned
//! directory under `.zig-cache/tmp`.

const std = @import("std");
const builtin = @import("builtin");
const build_options = @import("build_options");

const RFC_VECTORS = [_]struct { raw: []const u8, encoded: []const u8 }{
    .{ .raw = "", .encoded = "" },
    .{ .raw = "f", .encoded = "Zg==" },
    .{ .raw = "fo", .encoded = "Zm8=" },
    .{ .raw = "foo", .encoded = "Zm9v" },
    .{ .raw = "foob", .encoded = "Zm9vYg==" },
    .{ .raw = "fooba", .encoded = "Zm9vYmE=" },
    .{ .raw = "foobar", .encoded = "Zm9vYmFy" },
};

test "[cli] - [custom-base64]: converts RFC 4648 vectors in every mode" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    for (RFC_VECTORS, 0..) |vector, index| {
        const raw_path = try writeInput(arena.allocator(), &tmp, "raw", index, vector.raw);
        const encoded_path = try writeInput(arena.allocator(), &tmp, "b64", index, vector.encoded);
        const runs = [_]struct { args: []const []const u8, expected: []const u8 }{
            .{ .args = &.{ "--mode", "encode-memory", raw_path }, .expected = vector.encoded },
            .{ .args = &.{ "--mode", "decode-memory", encoded_path }, .expected = vector.raw },
            .{ .args = &.{ "--mode", "encode-streaming", raw_path }, .expected = vector.encoded },
            .{ .args = &.{ "--mode", "decode-streaming", encoded_path }, .expected = vector.raw },
            .{ .args = &.{ "--mode", "encode-streaming", "--chunk", "1", raw_path }, .expected = vector.encoded },
            .{ .args = &.{ "--mode", "decode-streaming", "--chunk", "1", encoded_path }, .expected = vector.raw },
        };
        for (runs) |run| {
            const result = try runCli(arena.allocator(), run.args);
            try expectExit(0, result.term);
            try std.testing.expectEqualStrings(run.expected, result.stdout);
            try std.testing.expectEqualStrings("", result.stderr);
        }
    }
}

test "[cli] - [custom-base64]: reports decode errors by exact name in both modes" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    const cases = [_]struct { input: []const u8, error_line: []const u8 }{
        .{ .input = "YQ@=", .error_line = "error: InvalidCharacter" },
        .{ .input = "Y=Q=", .error_line = "error: InvalidPadding" },
        .{ .input = "YQ", .error_line = "error: InvalidPadding" },
        .{ .input = "YQ==\n", .error_line = "error: InvalidPadding" },
        .{ .input = "!AAAA===", .error_line = "error: InvalidCharacter" },
    };
    for (cases, 0..) |case, index| {
        const path = try writeInput(arena.allocator(), &tmp, "bad", index, case.input);
        for ([_][]const u8{ "decode-memory", "decode-streaming" }) |mode| {
            const result = try runCli(arena.allocator(), &.{ "--mode", mode, path });
            try expectExit(1, result.term);
            try std.testing.expectEqualStrings("", result.stdout);
            try std.testing.expectEqualStrings(case.error_line, firstLine(result.stderr));
        }
    }
}

test "[cli] - [custom-base64]: rejects invalid arguments with usage" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    const path = try writeInput(arena.allocator(), &tmp, "raw", 0, "foo");
    const argument_sets = [_][]const []const u8{
        &.{},
        &.{ "--mode", "encode-one-shot", path },
        &.{ "--mode", "decode-one-shot", path },
        &.{ "--mode", "encode-memory" },
        &.{ "--chunk", "0", path },
        &.{ "--mode", "encode-memory", "--chunk", "1", path },
        &.{ "--iterations", "1", path },
        &.{ "--expected-probe", "1", path },
        &.{ "--raw", path },
        &.{ "--unknown", path },
        &.{ path, path },
    };
    for (argument_sets) |arguments| {
        const result = try runCli(arena.allocator(), arguments);
        try expectExit(1, result.term);
        try std.testing.expectEqualStrings("", result.stdout);
        try std.testing.expect(std.mem.startsWith(u8, result.stderr, "usage: custom-base64"));
        try std.testing.expect(std.mem.indexOf(u8, result.stderr, "error: InvalidArguments") != null);
    }
}

test "[cli] - [custom-base64]: memory and streaming modes write exact bytes" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    var raw: [70_000]u8 = undefined;
    for (&raw, 0..) |*byte, index| byte.* = @truncate(index * 131 + (index >> 7));
    var encoded: [std.base64.standard.Encoder.calcSize(raw.len)]u8 = undefined;
    _ = std.base64.standard.Encoder.encode(&encoded, &raw);
    const raw_path = try writeInput(arena.allocator(), &tmp, "raw", 0, &raw);
    const encoded_path = try writeInput(arena.allocator(), &tmp, "b64", 0, &encoded);

    const pairs = [_]struct {
        memory: []const u8,
        streaming: []const u8,
        path: []const u8,
        expected: []const u8,
    }{
        .{ .memory = "encode-memory", .streaming = "encode-streaming", .path = raw_path, .expected = &encoded },
        .{ .memory = "decode-memory", .streaming = "decode-streaming", .path = encoded_path, .expected = &raw },
    };
    for (pairs) |pair| {
        const memory = try runCli(arena.allocator(), &.{ "--mode", pair.memory, pair.path });
        const streaming = try runCli(arena.allocator(), &.{ "--mode", pair.streaming, pair.path });
        try expectExit(0, memory.term);
        try expectExit(0, streaming.term);
        try std.testing.expectEqualSlices(u8, pair.expected, memory.stdout);
        try std.testing.expectEqualSlices(u8, pair.expected, streaming.stdout);
    }
}

test "[cli] - [custom-base64]: converts empty input in every mode" {
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    const path = try writeInput(arena.allocator(), &tmp, "empty", 0, "");
    for ([_][]const u8{ "encode-memory", "decode-memory", "encode-streaming", "decode-streaming" }) |mode| {
        const result = try runCli(arena.allocator(), &.{ "--mode", mode, path });
        try expectExit(0, result.term);
        try std.testing.expectEqualStrings("", result.stdout);
        try std.testing.expectEqualStrings("", result.stderr);
    }
}

test "[cli] - [custom-base64]: memory mode reads files that report size zero" {
    if (builtin.os.tag != .linux) return error.SkipZigTest;
    var arena: std.heap.ArenaAllocator = .init(std.testing.allocator);
    defer arena.deinit();

    // `/proc` files report size zero, so the command must read them to EOF.
    const proc_path = "/proc/version";
    var file = try std.Io.Dir.openFileAbsolute(std.testing.io, proc_path, .{});
    defer file.close(std.testing.io);
    var reader = file.readerStreaming(std.testing.io, &.{});
    const raw = try reader.interface.allocRemaining(arena.allocator(), .unlimited);
    try std.testing.expect(raw.len != 0);
    const expected = try arena.allocator().alloc(u8, std.base64.standard.Encoder.calcSize(raw.len));
    _ = std.base64.standard.Encoder.encode(expected, raw);

    const result = try runCli(arena.allocator(), &.{ "--mode", "encode-memory", proc_path });
    try expectExit(0, result.term);
    try std.testing.expectEqualStrings(expected, result.stdout);
}

fn runCli(allocator: std.mem.Allocator, arguments: []const []const u8) !std.process.RunResult {
    const argv = try allocator.alloc([]const u8, arguments.len + 1);
    argv[0] = build_options.exe_path;
    @memcpy(argv[1..], arguments);
    return std.process.run(allocator, std.testing.io, .{ .argv = argv });
}

/// Writes `bytes` to the test directory and returns a path the child process can open from the
/// shared working directory.
fn writeInput(
    allocator: std.mem.Allocator,
    tmp: *std.testing.TmpDir,
    stem: []const u8,
    index: usize,
    bytes: []const u8,
) ![]const u8 {
    const name = try std.fmt.allocPrint(allocator, "{s}-{d}", .{ stem, index });
    try tmp.dir.writeFile(std.testing.io, .{ .sub_path = name, .data = bytes });
    return std.fmt.allocPrint(allocator, ".zig-cache/tmp/{s}/{s}", .{ tmp.sub_path, name });
}

fn expectExit(expected: u8, term: std.process.Child.Term) !void {
    try std.testing.expectEqual(std.process.Child.Term{ .exited = expected }, term);
}

fn firstLine(text: []const u8) []const u8 {
    return text[0 .. std.mem.indexOfScalar(u8, text, '\n') orelse text.len];
}
