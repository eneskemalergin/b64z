//! Command-line adapter for the custom Base64 codec and the local benchmark jobs.
//!
//! Each run converts one input file. Memory modes read the whole file into one buffer and
//! convert it in place; streaming modes reuse fixed stack buffers. Output goes to standard
//! output as raw bytes or as a result line with an output probe. Diagnostics go to standard
//! error. On Linux, memory modes ask for transparent huge pages for their whole-input buffer.

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

    // Repeated runs without written output keep the probe so conversions stay observable.
    const track_probe = !request.raw or request.iterations > 1;
    var result: Conversion = undefined;
    var sink: u64 = 0;
    for (0..request.iterations) |iteration| {
        const last = iteration + 1 == request.iterations;
        const destination: ?*Io.Writer = if (request.raw and last) stdout else null;
        result = if (request.mode.streaming())
            try convertStreaming(io, request, track_probe, destination)
        else
            try convertMemory(allocator, io, request, track_probe, destination);
        sink ^= result.probe;
        std.mem.doNotOptimizeAway(sink);
    }

    if (request.raw) return stdout.flush();
    if (request.expected_probe) |expected| {
        if (result.probe != expected) return error.OutputProbeMismatch;
        return;
    }
    try stdout.print(
        "candidate=zig-custom-v1 variant={s} mode={s} bytes={d} output_bytes={d} " ++
            "iterations={d} probe={x:0>16} sink={x:0>16} backend=zig-{s}\n",
        .{
            VARIANT,
            request.mode.label(),
            result.input_bytes,
            result.output_bytes,
            request.iterations,
            result.probe,
            sink,
            @tagName(base64.BACKEND),
        },
    );
    try stdout.flush();
}

const VERSION = "0.1.0";
const VARIANT = "Base64/RFC4648";
const STREAM_INPUT_SIZE = 64 * 1024;
const STREAM_OUTPUT_SIZE = 88 * 1024;
const PROBE_OFFSET: u64 = 1469598103934665603;
const PROBE_PRIME: u64 = 1099511628211;

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
    iterations: usize = 1,
    input_path: []const u8,
    raw: bool = false,
    expected_probe: ?u64 = null,
};

const Conversion = struct {
    input_bytes: usize,
    output_bytes: usize,
    probe: u64,
};

fn convertMemory(
    allocator: std.mem.Allocator,
    io: Io,
    request: Request,
    track_probe: bool,
    destination: ?*Io.Writer,
) !Conversion {
    var file = try openInputFile(io, request.input_path);
    defer file.close(io);
    const encoding = request.mode.encoding();
    const whole = try readWhole(allocator, io, file, encoding);
    defer allocator.free(whole.buffer);

    const output_len = if (encoding)
        try base64.encodeInPlace(whole.buffer, whole.input_len)
    else
        try base64.decodeInPlace(whole.buffer[0..whole.input_len]);
    var probe: Probe = .init(output_len);
    try emit(&probe, whole.buffer[0..output_len], track_probe, destination);
    return .{
        .input_bytes = whole.input_len,
        .output_bytes = output_len,
        .probe = if (track_probe) probe.finish() else 0,
    };
}

fn convertStreaming(
    io: Io,
    request: Request,
    track_probe: bool,
    destination: ?*Io.Writer,
) !Conversion {
    var input_buffer: [STREAM_INPUT_SIZE]u8 = undefined;
    var output_buffer: [STREAM_OUTPUT_SIZE]u8 = undefined;
    var file = try openInputFile(io, request.input_path);
    defer file.close(io);

    const encoding = request.mode.encoding();
    const input_bytes = std.math.cast(usize, (try file.stat(io)).size) orelse
        return error.InputTooLarge;
    const output_bytes = if (encoding)
        try base64.encodedSize(input_bytes)
    else
        try streamingDecodedSize(io, file, input_bytes);
    var probe: Probe = .init(output_bytes);
    var reader = file.reader(io, &.{});
    var encoder: base64.Encoder = .{};
    var decoder: base64.Decoder = .{};
    var bytes_read: usize = 0;

    while (true) {
        const read_len = try reader.interface.readSliceShort(&input_buffer);
        if (read_len == 0) break;
        bytes_read += read_len;

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
        try emit(&probe, output_buffer[0..output_len], track_probe, destination);
    }

    const final_len = if (encoding)
        try encoder.final(&output_buffer)
    else
        try decoder.final(&output_buffer);
    try emit(&probe, output_buffer[0..final_len], track_probe, destination);
    if (bytes_read != input_bytes) return error.InputChanged;
    if (probe.output_offset != output_bytes) return error.OutputLengthMismatch;
    return .{
        .input_bytes = input_bytes,
        .output_bytes = output_bytes,
        .probe = if (track_probe) probe.finish() else 0,
    };
}

fn emit(probe: *Probe, data: []const u8, track_probe: bool, destination: ?*Io.Writer) !void {
    probe.feed(data, track_probe);
    if (destination) |writer| try writer.writeAll(data);
}

/// FNV-1a over the output length, every 64th output byte, and the last output byte. Sample
/// positions depend only on output offsets, so memory and streaming runs report equal probes.
const Probe = struct {
    value: u64 = PROBE_OFFSET,
    output_offset: usize = 0,
    next_sample: usize = 0,
    last_byte: ?u8 = null,

    fn init(output_len: usize) Probe {
        var probe: Probe = .{};
        const length: u64 = output_len;
        for (0..8) |shift| probe.mix(@truncate(length >> @intCast(shift * 8)));
        return probe;
    }

    fn mix(self: *Probe, byte: u8) void {
        self.value ^= byte;
        self.value *%= PROBE_PRIME;
    }

    fn feed(self: *Probe, data: []const u8, track_probe: bool) void {
        if (track_probe) {
            while (self.next_sample < self.output_offset + data.len) : (self.next_sample += 64) {
                self.mix(data[self.next_sample - self.output_offset]);
            }
            if (data.len != 0) self.last_byte = data[data.len - 1];
        }
        self.output_offset += data.len;
    }

    fn finish(self: *Probe) u64 {
        if (self.last_byte) |byte| self.mix(byte);
        return self.value;
    }
};

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

/// Returns the decoded length from the file size and the final group, so the probe can hash it
/// before streaming. Malformed input gets an estimate; decoding then fails in input order.
fn streamingDecodedSize(io: Io, file: Io.File, input_bytes: usize) !usize {
    if (input_bytes < 4 or input_bytes % 4 != 0) return input_bytes / 4 * 3;
    var tail: [4]u8 = undefined;
    if (try file.readPositionalAll(io, &tail, input_bytes - 4) != tail.len) {
        return error.InputChanged;
    }
    return input_bytes / 4 * 3 - 3 + (base64.decodedSize(&tail) catch 3);
}

fn openInputFile(io: Io, path: []const u8) !Io.File {
    if (std.fs.path.isAbsolute(path)) return Io.Dir.openFileAbsolute(io, path, .{});
    return Io.Dir.cwd().openFile(io, path, .{});
}

fn usage() error{InvalidArguments} {
    std.debug.print(
        \\usage: custom-base64 --version
        \\       custom-base64 [--mode MODE] [--chunk N] [--iterations N]
        \\           [--raw | --expected-probe HEX] INPUT
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
        } else if (std.mem.eql(u8, arg, "--iterations")) {
            const value = args.next() orelse return error.InvalidArguments;
            request.iterations = try parsePositive(value);
        } else if (std.mem.eql(u8, arg, "--raw")) {
            request.raw = true;
        } else if (std.mem.eql(u8, arg, "--expected-probe")) {
            const value = args.next() orelse return error.InvalidArguments;
            const text = if (std.mem.startsWith(u8, value, "0x")) value[2..] else value;
            request.expected_probe = try std.fmt.parseInt(u64, text, 16);
        } else if (arg.len == 0 or arg[0] == '-') {
            return error.InvalidArguments;
        } else if (request.input_path.len != 0) {
            return error.InvalidArguments;
        } else {
            request.input_path = arg;
        }
        current = args.next();
    }
    if (request.input_path.len == 0 or (request.raw and request.expected_probe != null)) {
        return error.InvalidArguments;
    }
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
