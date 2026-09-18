//! Command-line adapter for the custom Base64 codec and the local benchmark jobs.

const std = @import("std");
const base64 = @import("base64.zig");

const Io = std.Io;
const VERSION = "0.1.0";
const VARIANT = "Base64/RFC4648";
const STREAM_INPUT_SIZE = 64 * 1024;
const STREAM_OUTPUT_SIZE = 88 * 1024;

const Mode = enum {
    encode_memory,
    decode_memory,
    encode_streaming,
    decode_streaming,
};

const Request = struct {
    mode: Mode = .encode_memory,
    chunk_size: usize = 64 * 1024,
    iterations: usize = 1,
    input_path: []const u8,
    raw: bool = false,
    expected_probe: ?u64 = null,
};

pub fn main(init: std.process.Init.Minimal) !void {
    var threaded: std.Io.Threaded = .init_single_threaded;
    const io = threaded.io();
    const allocator = std.heap.page_allocator;
    var args = try std.process.Args.Iterator.initAllocator(init.args, allocator);
    defer args.deinit();
    _ = args.next();
    const first = args.next() orelse return usage();
    if (std.mem.eql(u8, first, "--version")) return printVersion(io);

    const request = parseRequest(first, &args) catch return usage();
    if (isStreaming(request.mode)) return runStreaming(io, request);

    const input = try readInput(io, allocator, request.input_path);
    defer allocator.free(input);

    const encoding = switch (request.mode) {
        .encode_memory, .encode_streaming => true,
        .decode_memory, .decode_streaming => false,
    };
    const output_capacity = if (encoding)
        try base64.encodedSize(input.len)
    else
        try base64.decodedSize(input);
    const output = try allocator.alloc(u8, @max(output_capacity, 1));
    defer allocator.free(output);

    var output_len: usize = 0;
    var probe: u64 = 0;
    var sink: u64 = 0;
    const track_probe = !request.raw or request.iterations > 1;
    var iteration: usize = 0;
    while (iteration < request.iterations) : (iteration += 1) {
        output_len = try apply(request.mode, input, request.chunk_size, output);
        if (track_probe) {
            probe = @call(.never_inline, outputProbe, .{output[0..output_len]});
            std.mem.doNotOptimizeAway(probe);
            sink ^= probe;
            std.mem.doNotOptimizeAway(sink);
        }
        std.mem.doNotOptimizeAway(output.ptr);
    }

    if (request.raw) {
        try writeBytes(io, output[0..output_len]);
        return;
    }
    if (request.expected_probe) |expected| {
        if (probe != expected) return error.OutputProbeMismatch;
    }
    if (request.expected_probe != null) return;
    try printResult(io, request.mode, input.len, output_len, request.iterations, probe, sink);
}

fn isStreaming(mode: Mode) bool {
    return mode == .encode_streaming or mode == .decode_streaming;
}

fn runStreaming(io: Io, request: Request) !void {
    var input_buffer: [STREAM_INPUT_SIZE]u8 = undefined;
    var output_buffer: [STREAM_OUTPUT_SIZE]u8 = undefined;
    var stdout_buffer: [4096]u8 = undefined;
    var stdout = std.Io.File.stdout().writer(io, &stdout_buffer);

    var input_bytes: usize = 0;
    var output_len: usize = 0;
    var probe: u64 = 0;
    var sink: u64 = 0;
    const track_probe = !request.raw or request.iterations > 1;
    var iteration: usize = 0;
    while (iteration < request.iterations) : (iteration += 1) {
        const writer: ?*Io.Writer = if (request.raw and iteration + 1 == request.iterations)
            &stdout.interface
        else
            null;
        const result = try streamIteration(
            io,
            request,
            &input_buffer,
            &output_buffer,
            writer,
        );
        input_bytes = result.input_bytes;
        output_len = result.output_bytes;
        probe = result.probe;
        if (track_probe) {
            std.mem.doNotOptimizeAway(probe);
            sink ^= probe;
            std.mem.doNotOptimizeAway(sink);
        }
        std.mem.doNotOptimizeAway(&output_buffer);
    }

    if (request.raw) {
        try stdout.interface.flush();
        return;
    }
    if (request.expected_probe) |expected| {
        if (probe != expected) return error.OutputProbeMismatch;
    }
    if (request.expected_probe != null) return;
    try printResult(io, request.mode, input_bytes, output_len, request.iterations, probe, sink);
}

const StreamingProbe = struct {
    value: u64,
    output_offset: usize = 0,
    next_sample: usize = 0,
    last_byte: u8 = 0,
    has_last_byte: bool = false,

    fn init(output_len: usize) StreamingProbe {
        var probe = StreamingProbe{ .value = 1469598103934665603 };
        const prime: u64 = 1099511628211;
        const length: u64 = @intCast(output_len);
        var shift: usize = 0;
        while (shift < 8) : (shift += 1) {
            const length_byte: u8 = @truncate(length >> @intCast(shift * 8));
            probe.value ^= length_byte;
            probe.value *%= prime;
        }
        return probe;
    }

    fn feed(self: *StreamingProbe, data: []const u8, track_probe: bool) void {
        const prime: u64 = 1099511628211;
        if (track_probe) {
            while (self.next_sample < self.output_offset + data.len) {
                if (self.next_sample < self.output_offset) self.next_sample = self.output_offset;
                self.value ^= data[self.next_sample - self.output_offset];
                self.value *%= prime;
                self.next_sample += 64;
            }
            if (data.len != 0) {
                self.last_byte = data[data.len - 1];
                self.has_last_byte = true;
            }
        }
        self.output_offset += data.len;
    }

    fn finish(self: *StreamingProbe) u64 {
        if (self.has_last_byte) {
            const prime: u64 = 1099511628211;
            self.value ^= self.last_byte;
            self.value *%= prime;
        }
        return self.value;
    }
};

const StreamingResult = struct {
    input_bytes: usize,
    output_bytes: usize,
    probe: u64,
};

fn streamIteration(
    io: Io,
    request: Request,
    input_buffer: []u8,
    output_buffer: []u8,
    writer: ?*Io.Writer,
) !StreamingResult {
    var file = try openInputFile(io, request.input_path);
    defer file.close(io);
    const stat = try file.stat(io);
    const input_bytes: usize = std.math.cast(usize, stat.size) orelse return error.InputTooLarge;
    const output_bytes = try streamingOutputSize(io, file, request.mode, input_bytes);
    const track_probe = !request.raw or request.iterations > 1;
    var probe = StreamingProbe.init(output_bytes);
    var reader = file.reader(io, &.{});
    var encoder: base64.Encoder = .{};
    var decoder: base64.Decoder = .{};
    var bytes_read: usize = 0;
    var pending_output: usize = 0;

    while (true) {
        const read_len = try reader.interface.readSliceShort(input_buffer);
        if (read_len == 0) break;
        var chunk_index: usize = 0;
        if (request.chunk_size <= 3) {
            while (chunk_index < read_len) {
                const written = switch (request.mode) {
                    .encode_streaming => try encoder.updateByte(input_buffer[chunk_index], output_buffer[pending_output..]),
                    .decode_streaming => try decoder.updateByte(input_buffer[chunk_index], output_buffer[pending_output..]),
                    else => unreachable,
                };
                pending_output += written;
                chunk_index += 1;
                bytes_read += 1;
            }
        } else {
            while (chunk_index < read_len) {
                const chunk_len = @min(request.chunk_size, read_len - chunk_index);
                const input_chunk = input_buffer[chunk_index..][0..chunk_len];
                const written = switch (request.mode) {
                    .encode_streaming => try encoder.update(input_chunk, output_buffer[pending_output..]),
                    .decode_streaming => try decoder.update(input_chunk, output_buffer[pending_output..]),
                    else => unreachable,
                };
                pending_output += written;
                chunk_index += chunk_len;
                bytes_read += chunk_len;
            }
        }
        if (pending_output != 0) {
            try emitStreaming(output_buffer[0..pending_output], &probe, track_probe, writer);
            pending_output = 0;
        }
    }

    const written = switch (request.mode) {
        .encode_streaming => try encoder.final(output_buffer[pending_output..]),
        .decode_streaming => try decoder.final(output_buffer[pending_output..]),
        else => unreachable,
    };
    pending_output += written;
    try emitStreaming(output_buffer[0..pending_output], &probe, track_probe, writer);
    if (bytes_read != input_bytes) return error.InputChanged;
    if (probe.output_offset != output_bytes) return error.OutputLengthMismatch;
    return .{
        .input_bytes = input_bytes,
        .output_bytes = output_bytes,
        .probe = if (track_probe) probe.finish() else 0,
    };
}

fn emitStreaming(data: []const u8, probe: *StreamingProbe, track_probe: bool, writer: ?*Io.Writer) !void {
    probe.feed(data, track_probe);
    if (writer) |destination| try destination.writeAll(data);
}

fn openInputFile(io: Io, path: []const u8) !Io.File {
    if (std.fs.path.isAbsolute(path)) return std.Io.Dir.openFileAbsolute(io, path, .{});
    return std.Io.Dir.cwd().openFile(io, path, .{});
}

fn streamingOutputSize(io: Io, file: Io.File, mode: Mode, input_bytes: usize) !usize {
    return switch (mode) {
        .encode_streaming => base64.encodedSize(input_bytes),
        .decode_streaming => streamingDecodedSize(io, file, input_bytes),
        else => unreachable,
    };
}

fn streamingDecodedSize(io: Io, file: Io.File, input_bytes: usize) !usize {
    if (input_bytes % 4 != 0) return error.InvalidPadding;
    if (input_bytes == 0) return 0;

    var tail: [4]u8 = undefined;
    const read = try file.readPositionalAll(io, &tail, @intCast(input_bytes - 4));
    if (read != tail.len) return error.InputChanged;
    const tail_size = try base64.decodedSize(&tail);
    const groups = input_bytes / 4;
    if (groups - 1 > (std.math.maxInt(usize) - tail_size) / 3) return error.InputTooLarge;
    return (groups - 1) * 3 + tail_size;
}

fn usage() error{InvalidArguments} {
    std.debug.print(
        \\usage: custom-base64 --version
        \\       custom-base64 --mode encode-memory|decode-memory|encode-streaming|decode-streaming
        \\           --chunk N --iterations N [--raw|--expected-probe HEX] INPUT
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
            request.mode = parseMode(value) orelse return error.InvalidArguments;
        } else if (std.mem.eql(u8, arg, "--chunk")) {
            request.chunk_size = try parsePositive(args.next() orelse return error.InvalidArguments);
        } else if (std.mem.eql(u8, arg, "--iterations")) {
            request.iterations = try parsePositive(args.next() orelse return error.InvalidArguments);
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

fn parseMode(value: []const u8) ?Mode {
    if (std.mem.eql(u8, value, "encode-memory")) return .encode_memory;
    if (std.mem.eql(u8, value, "decode-memory")) return .decode_memory;
    if (std.mem.eql(u8, value, "encode-streaming")) return .encode_streaming;
    if (std.mem.eql(u8, value, "decode-streaming")) return .decode_streaming;
    return null;
}

fn parsePositive(value: []const u8) !usize {
    const parsed = std.fmt.parseInt(usize, value, 10) catch return error.InvalidArguments;
    if (parsed == 0) return error.InvalidArguments;
    return parsed;
}

fn readInput(io: Io, allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    if (!std.fs.path.isAbsolute(path)) return std.Io.Dir.cwd().readFileAlloc(io, path, allocator, .unlimited);
    var file = try std.Io.Dir.openFileAbsolute(io, path, .{});
    defer file.close(io);
    var reader = file.reader(io, &.{});
    return reader.interface.allocRemaining(allocator, .unlimited);
}

fn apply(mode: Mode, input: []const u8, chunk_size: usize, output: []u8) !usize {
    return switch (mode) {
        .encode_memory => base64.encode(input, output),
        .decode_memory => base64.decode(input, output),
        .encode_streaming => encodeStreaming(input, chunk_size, output),
        .decode_streaming => decodeStreaming(input, chunk_size, output),
    };
}

fn encodeStreaming(input: []const u8, chunk_size: usize, output: []u8) !usize {
    var encoder: base64.Encoder = .{};
    var input_index: usize = 0;
    var output_index: usize = 0;

    while (input_index < input.len) {
        const chunk_len = @min(input.len - input_index, chunk_size);
        output_index += try encoder.update(input[input_index..][0..chunk_len], output[output_index..]);
        input_index += chunk_len;
    }

    output_index += try encoder.final(output[output_index..]);
    return output_index;
}

fn decodeStreaming(input: []const u8, chunk_size: usize, output: []u8) !usize {
    var decoder: base64.Decoder = .{};
    var input_index: usize = 0;
    var output_index: usize = 0;

    while (input_index < input.len) {
        const chunk_len = @min(input.len - input_index, chunk_size);
        output_index += try decoder.update(input[input_index..][0..chunk_len], output[output_index..]);
        input_index += chunk_len;
    }

    output_index += try decoder.final(output[output_index..]);
    return output_index;
}

fn outputProbe(data: []const u8) u64 {
    var value: u64 = 1469598103934665603;
    const prime: u64 = 1099511628211;
    const length: u64 = @intCast(data.len);
    var shift: usize = 0;
    while (shift < 8) : (shift += 1) {
        const length_byte: u8 = @truncate(length >> @intCast(shift * 8));
        value ^= length_byte;
        value *%= prime;
    }
    var index: usize = 0;
    while (index < data.len) : (index += 64) {
        value ^= data[index];
        value *%= prime;
    }
    if (data.len != 0) {
        value ^= data[data.len - 1];
        value *%= prime;
    }
    return value;
}

fn writeBytes(io: Io, data: []const u8) !void {
    var buffer: [4096]u8 = undefined;
    var stdout = std.Io.File.stdout().writer(io, &buffer);
    try stdout.interface.writeAll(data);
    try stdout.interface.flush();
}

fn printVersion(io: Io) !void {
    var buffer: [64]u8 = undefined;
    var stdout = std.Io.File.stdout().writer(io, &buffer);
    try stdout.interface.print("custom-base64 {s} backend={s}\n", .{ VERSION, @tagName(base64.BACKEND) });
    try stdout.interface.flush();
}

fn printResult(io: Io, mode: Mode, bytes: usize, output_bytes: usize, iterations: usize, probe: u64, sink: u64) !void {
    var buffer: [256]u8 = undefined;
    var stdout = std.Io.File.stdout().writer(io, &buffer);
    const mode_text = switch (mode) {
        .encode_memory => "encode-memory",
        .decode_memory => "decode-memory",
        .encode_streaming => "encode-streaming",
        .decode_streaming => "decode-streaming",
    };
    try stdout.interface.print(
        "candidate=zig-custom-v1 variant={s} mode={s} bytes={d} output_bytes={d} iterations={d} probe={x:0>16} sink={x:0>16} backend=zig-{s}\n",
        .{ VARIANT, mode_text, bytes, output_bytes, iterations, probe, sink, @tagName(base64.BACKEND) },
    );
    try stdout.interface.flush();
}
