//! Comparison peer: a file adapter around Zig's standard-library Base64 codec.
//!
//! It is not part of B64Z. It reads the whole input file, calls `std.base64.standard` unchanged,
//! and writes the result to standard output. `--decode` selects decoding; `--encode` or no flag
//! selects encoding.

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
    const decode = std.mem.eql(u8, first, "--decode");
    const input_path = if (decode or std.mem.eql(u8, first, "--encode"))
        args.next() orelse return usage()
    else
        first;
    if (args.next() != null) return usage();

    const input = try Io.Dir.cwd().readFileAlloc(io, input_path, allocator, .unlimited);
    defer allocator.free(input);

    const codec = std.base64.standard;
    const output_len = if (decode)
        try codec.Decoder.calcSizeForSlice(input)
    else
        codec.Encoder.calcSize(input.len);
    const output = try allocator.alloc(u8, output_len);
    defer allocator.free(output);
    if (decode) {
        try codec.Decoder.decode(output, input);
    } else {
        _ = codec.Encoder.encode(output, input);
    }

    var stdout_buffer: [4096]u8 = undefined;
    var stdout = Io.File.stdout().writer(io, &stdout_buffer);
    try stdout.interface.writeAll(output);
    try stdout.interface.flush();
}

fn usage() error{InvalidArguments} {
    std.debug.print("usage: zig-std-base64 [--encode | --decode] INPUT\n", .{});
    return error.InvalidArguments;
}
