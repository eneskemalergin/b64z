//! Command-line adapter for the custom Base64 codec.
//!
//! Each run converts one input file. Memory modes read the whole file into one buffer and
//! convert it in place; streaming modes reuse fixed stack buffers. Converted bytes go to
//! standard output and diagnostics go to standard error. On Linux, memory modes ask for
//! transparent huge pages for their whole-input buffer.

const std = @import("std");
const builtin = @import("builtin");

const base64 = @import("base64");

const Io = std.Io;

// Only the segfault handler uses the alternate signal stack. Release builds omit the handler,
// so they also skip the stack's 256 KiB of resident memory.
pub const std_options: std.Options = .{
    .signal_stack_size = if (std.debug.default_enable_segfault_handler)
        (std.Options{}).signal_stack_size
    else
        null,
};

pub fn main(init: std.process.Init.Minimal) !void {
    var threaded: Io.Threaded = .init_single_threaded;
    const io = threaded.io();
    const allocator = std.heap.page_allocator;
    var args = try std.process.Args.Iterator.initAllocator(init.args, allocator);
    defer args.deinit();
    _ = args.next();

    var stdout_buffer: [4096]u8 = undefined;
    var stdout_writer = Io.File.stdout().writer(io, &stdout_buffer);
    const stdout = &stdout_writer.interface;

    const first = args.next() orelse return usage();
    if (std.mem.eql(u8, first, "--version")) {
        try stdout.print("custom-base64 {s} backend={s} optimize={s} target={s}\n", .{
            VERSION,
            @tagName(base64.BACKEND),
            @tagName(builtin.mode),
            @tagName(builtin.target.cpu.arch),
        });
        return stdout.flush();
    }
    const request = parseRequest(first, &args) catch return usage();

    if (request.mode.streaming())
        try convertStreaming(io, request, stdout)
    else
        try convertMemory(allocator, io, request, stdout);
    return stdout.flush();
}

const VERSION = @import("build_options").version;
const STREAM_INPUT_SIZE = 64 * 1024;
const STREAM_OUTPUT_SIZE = 88 * 1024;

const Mode = enum {
    encode_memory,
    decode_memory,
    encode_streaming,
    decode_streaming,

    const LABELS = [_][]const u8{
        "encode-memory",
        "decode-memory",
        "encode-streaming",
        "decode-streaming",
    };

    fn parse(value: []const u8) ?Mode {
        for (LABELS, 0..) |label_text, index| {
            if (std.mem.eql(u8, value, label_text)) return @enumFromInt(index);
        }
        return null;
    }

    fn label(mode: Mode) []const u8 {
        return LABELS[@intFromEnum(mode)];
    }

    fn encoding(mode: Mode) bool {
        return mode == .encode_memory or mode == .encode_streaming;
    }

    fn streaming(mode: Mode) bool {
        return mode == .encode_streaming or mode == .decode_streaming;
    }
};

const Request = struct {
    mode: Mode = .encode_memory,
    chunk_size: usize = STREAM_INPUT_SIZE,
    chunk_explicit: bool = false,
    input_path: []const u8,
};

fn convertMemory(
    allocator: std.mem.Allocator,
    io: Io,
    request: Request,
    destination: *Io.Writer,
) !void {
    var file = try openInputFile(io, request.input_path);
    defer file.close(io);
    const encoding = request.mode.encoding();
    const whole = try readWhole(allocator, io, file, encoding);
    defer allocator.free(whole.buffer);

    const output_len = if (encoding)
        try base64.encodeInPlace(whole.buffer, whole.input_len)
    else
        try base64.decodeInPlace(whole.buffer[0..whole.input_len]);
    try destination.writeAll(whole.buffer[0..output_len]);
}

fn convertStreaming(
    io: Io,
    request: Request,
    destination: *Io.Writer,
) !void {
    var input_buffer: [STREAM_INPUT_SIZE]u8 = undefined;
    var output_buffer: [STREAM_OUTPUT_SIZE]u8 = undefined;
    var file = try openInputFile(io, request.input_path);
    defer file.close(io);

    const encoding = request.mode.encoding();
    const input_bytes = std.math.cast(usize, (try file.stat(io)).size) orelse
        return error.InputTooLarge;
    const expected_output_bytes: ?usize = if (encoding)
        try base64.encodedSize(input_bytes)
    else
        null;
    var reader = file.reader(io, &.{});
    var encoder: base64.Encoder = .{};
    var decoder: base64.Decoder = .{};
    var bytes_read: usize = 0;
    var output_bytes: usize = 0;

    while (true) {
        const read_len = try reader.interface.readSliceShort(&input_buffer);
        if (read_len == 0) break;
        bytes_read = std.math.add(usize, bytes_read, read_len) catch return error.InputChanged;

        var output_len: usize = 0;
        var chunk_start: usize = 0;
        while (chunk_start < read_len) {
            const chunk_len = @min(request.chunk_size, read_len - chunk_start);
            const chunk = input_buffer[chunk_start..][0..chunk_len];
            const output = output_buffer[output_len..];
            output_len += if (encoding)
                try encoder.update(chunk, output)
            else
                try decoder.update(chunk, output);
            chunk_start += chunk_len;
        }
        output_bytes = try emit(
            output_bytes,
            output_buffer[0..output_len],
            expected_output_bytes,
            destination,
        );
    }

    const final_len = if (encoding)
        try encoder.final(&output_buffer)
    else
        try decoder.final(&output_buffer);
    output_bytes = try emit(
        output_bytes,
        output_buffer[0..final_len],
        expected_output_bytes,
        destination,
    );
    if (bytes_read != input_bytes) return error.InputChanged;
    if (expected_output_bytes) |expected| {
        if (output_bytes != expected) return error.OutputLengthMismatch;
    }
}

fn emit(
    output_bytes: usize,
    data: []const u8,
    expected_output_bytes: ?usize,
    destination: *Io.Writer,
) !usize {
    const next_output_bytes = std.math.add(usize, output_bytes, data.len) catch
        return error.OutputLengthMismatch;
    if (expected_output_bytes) |expected| {
        if (next_output_bytes > expected) return error.OutputLengthMismatch;
    }
    try destination.writeAll(data);
    return next_output_bytes;
}

const WholeInput = struct {
    buffer: []u8,
    input_len: usize,
};

/// Reads the whole file into one buffer sized for in-place conversion. The caller frees
/// `buffer` with `allocator`. Files without a known size, such as pipes and `/proc` entries,
/// are read to EOF and then resized.
fn readWhole(allocator: std.mem.Allocator, io: Io, file: Io.File, encoding: bool) !WholeInput {
    const stat = try file.stat(io);
    if (stat.kind == .file and stat.size != 0) {
        const input_len = std.math.cast(usize, stat.size) orelse return error.InputTooLarge;
        const buffer = try allocator.alloc(u8, try wholeCapacity(input_len, encoding));
        errdefer allocator.free(buffer);
        adviseHugePages(buffer);
        const read_len = try file.readPositionalAll(io, buffer[0..input_len], 0);
        if (read_len != input_len) return error.InputChanged;
        return .{ .buffer = buffer, .input_len = input_len };
    }

    var reader = file.readerStreaming(io, &.{});
    const input = try reader.interface.allocRemaining(allocator, .unlimited);
    errdefer allocator.free(input);
    const buffer = try allocator.realloc(input, try wholeCapacity(input.len, encoding));
    return .{ .buffer = buffer, .input_len = input.len };
}

fn wholeCapacity(input_len: usize, encoding: bool) !usize {
    return if (encoding) base64.encodedSize(input_len) else input_len;
}

fn openInputFile(io: Io, path: []const u8) !Io.File {
    if (std.fs.path.isAbsolute(path)) return Io.Dir.openFileAbsolute(io, path, .{});
    return Io.Dir.cwd().openFile(io, path, .{});
}

fn usage() error{InvalidArguments} {
    std.debug.print(
        \\usage: custom-base64 --version
        \\       custom-base64 [--mode MODE] [--chunk N] INPUT
        \\MODE: encode-memory (default), decode-memory, encode-streaming, decode-streaming
        \\
    , .{});
    return error.InvalidArguments;
}

fn parseRequest(first: []const u8, args: *std.process.Args.Iterator) !Request {
    var request = Request{ .input_path = "" };
    var current: ?[]const u8 = first;
    while (current) |arg| {
        if (std.mem.eql(u8, arg, "--mode")) {
            const value = args.next() orelse return error.InvalidArguments;
            request.mode = Mode.parse(value) orelse return error.InvalidArguments;
        } else if (std.mem.eql(u8, arg, "--chunk")) {
            const value = args.next() orelse return error.InvalidArguments;
            request.chunk_size = try parsePositive(value);
            request.chunk_explicit = true;
        } else if (arg.len == 0 or arg[0] == '-') {
            return error.InvalidArguments;
        } else if (request.input_path.len != 0) {
            return error.InvalidArguments;
        } else {
            request.input_path = arg;
        }
        current = args.next();
    }
    if (request.input_path.len == 0) return error.InvalidArguments;
    if (request.chunk_explicit and !request.mode.streaming()) return error.InvalidArguments;
    return request;
}

fn parsePositive(value: []const u8) !usize {
    const parsed = std.fmt.parseInt(usize, value, 10) catch return error.InvalidArguments;
    if (parsed == 0) return error.InvalidArguments;
    return parsed;
}

// --- Linux huge-page advice ---

const HUGE_PAGE_SIZE = 2 * 1024 * 1024;

/// Asks Linux to back the 2 MiB-aligned interior of a whole-input buffer with transparent huge
/// pages, so a small buffer never rounds up to a huge page. Call it before the first write.
/// Other targets, and kernels that refuse the advice, keep ordinary pages with the same bytes.
fn adviseHugePages(buffer: []u8) void {
    if (builtin.os.tag != .linux) return;
    const address = @intFromPtr(buffer.ptr);
    const start = std.mem.alignForward(usize, address, HUGE_PAGE_SIZE);
    const end = std.mem.alignBackward(usize, address + buffer.len, HUGE_PAGE_SIZE);
    if (end <= start) return;
    std.posix.madvise(@ptrFromInt(start), end - start, std.posix.MADV.HUGEPAGE) catch {};
}
