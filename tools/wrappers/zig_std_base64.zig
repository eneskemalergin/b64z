//! File adapter for Zig's standard-library Base64 codec.

const std = @import("std");

const Io = std.Io;

pub fn main(init: std.process.Init.Minimal) !void {
    var threaded: Io.Threaded = .init_single_threaded;
    const io = threaded.io();
    const allocator = std.heap.page_allocator;
    var args = try std.process.Args.Iterator.initAllocator(init.args, allocator);
    defer args.deinit();

    _ = args.next();
    const first = args.next() orelse return usage();
    var decode = false;
    const input_path = if (std.mem.eql(u8, first, "--decode")) blk: {
        decode = true;
        break :blk args.next() orelse return usage();
    } else if (std.mem.eql(u8, first, "--encode")) blk: {
        break :blk args.next() orelse return usage();
    } else first;
    if (args.next() != null) return usage();

    const input = try readInput(io, allocator, input_path);
    defer allocator.free(input);

    const output_capacity = if (decode)
        try std.base64.standard.Decoder.calcSizeForSlice(input)
    else
        std.base64.standard.Encoder.calcSize(input.len);
    const output = try allocator.alloc(u8, @max(output_capacity, 1));
    defer allocator.free(output);

    const result = if (decode) blk: {
        try std.base64.standard.Decoder.decode(output[0..output_capacity], input);
        break :blk output[0..output_capacity];
    } else std.base64.standard.Encoder.encode(output, input);
    try writeBytes(io, result);
}

fn usage() error{InvalidArguments} {
    std.debug.print("usage: zig-std-base64 [--decode] INPUT\n", .{});
    return error.InvalidArguments;
}

fn readInput(io: Io, allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    if (!std.fs.path.isAbsolute(path)) {
        return std.Io.Dir.cwd().readFileAlloc(io, path, allocator, .unlimited);
    }
    var file = try std.Io.Dir.openFileAbsolute(io, path, .{});
    defer file.close(io);
    var reader = file.reader(io, &.{});
    return reader.interface.allocRemaining(allocator, .unlimited);
}

fn writeBytes(io: Io, data: []const u8) !void {
    var buffer: [4096]u8 = undefined;
    var stdout = std.Io.File.stdout().writer(io, &buffer);
    try stdout.interface.writeAll(data);
    try stdout.interface.flush();
}
