# Command line

`custom-base64` reads one input file, writes converted bytes to standard output, and writes diagnostics to standard error.

```text
custom-base64 --version
custom-base64 [--mode MODE] [--chunk N] INPUT
```

The executable is installed at `zig-out/bin/custom-base64`; see [Getting started](Getting-Started) for the build commands.

## Choose a mode

- `encode-memory` reads the whole file and encodes it in place. This is the default when `--mode` is absent.
- `decode-memory` reads the whole encoded file and decodes it in place.
- `encode-streaming` encodes successive chunks through fixed buffers.
- `decode-streaming` decodes successive chunks through fixed buffers.

Use streaming for sequential conversion when you do not want storage to grow with file length. Whole-input conversion keeps the complete file in one allocated buffer. Encoding reserves room for the larger encoded result in that same buffer; decoding reuses the encoded input buffer.

Here, `memory` names the way the command processes the input. It is not the process memory measurement called peak RSS. The [benchmark method](Benchmarking#compared-operations) explains that measurement.

On Linux, whole-input conversion asks for transparent huge pages for large, known-size file buffers. This is a request, not a requirement: other systems and kernels that refuse it use ordinary pages with the same output.

```sh
./zig-out/bin/custom-base64 --mode encode-memory input.bin > encoded.b64
./zig-out/bin/custom-base64 --mode decode-memory encoded.b64 > decoded.bin
./zig-out/bin/custom-base64 --mode encode-streaming input.bin > streamed.b64
./zig-out/bin/custom-base64 --mode decode-streaming streamed.b64 > streamed.bin
```

Use different input and output paths: shell redirection truncates the output file before the converter opens its input. The input must remain unchanged during conversion. Use regular files for streaming: that path checks the bytes read against the file's reported size. Memory mode can also read files that report size zero by reading to EOF. `-` is not a standard-input option. Use `./-name` for a filename that begins with a hyphen.

## Chunk size

`--chunk N` sets the maximum bytes passed to each streaming codec update. `N` must be a positive integer. Memory modes reject this option.

```sh
./zig-out/bin/custom-base64 --mode encode-streaming --chunk 8191 input.bin > encoded.b64
```

The file-read buffer stays at 64 KiB, the output buffer at 88 KiB, and the stdout buffer at 4 KiB. A smaller `--chunk` divides each read into more update calls. A value above 64 KiB does not enlarge those buffers. The default is 65,536 bytes.

These are buffer capacities, not a promised RSS limit. Resident memory also includes the executable, stack, and runtime pages.

## Input and output rules

Encoding accepts arbitrary bytes and writes standard padded Base64 without line wrapping or a trailing newline. Decoding requires that exact format. It does not strip whitespace or accept URL-safe Base64. For example, `aGVsbG8=` is valid, but the same text followed by a newline is rejected.

A successful conversion exits with status `0`. Invalid arguments, malformed Base64, or an I/O failure produce a nonzero exit status and a diagnostic on stderr. There is no `--raw` option: stdout already contains only the converted bytes.

Streaming may write a valid prefix before a later error. Treat the entire output as incomplete after a failed command. Whole-input decode validates and converts before writing its result, but a later write failure can still leave partial output. Neither mode makes shell redirection all-or-nothing.

The old `encode-one-shot` and `decode-one-shot` names are rejected. Use `encode-memory` and `decode-memory`.

## Version and CPU selection

```sh
./zig-out/bin/custom-base64 --version
```

The output identifies the version, selected backend, optimization mode, and target architecture. An AVX2 build requires a CPU with the instructions selected at build time; it does not switch to scalar at runtime. The [build instructions](Getting-Started) explain how to select the scalar backend.
