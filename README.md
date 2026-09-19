# B64Z

Status: Active development.

B64Z is a strict RFC 4648 Base64 codec with caller-owned output buffers, memory and stateful streaming APIs, and an AVX2 fast path on x86-64.

Read the [Base64 API reference](docs/base64-api.md) for library, command-line, buffer, error, and backend rules.

The library source is [`src/base64.zig`](src/base64.zig). The command-line adapter is [`src/main.zig`](src/main.zig).

## Checks

Use Zig 0.16:

```sh
zig build test --summary all
zig build test -Dcpu=native -Doptimize=ReleaseFast --summary all
```

The retained benchmark results are in [`bench/linux-x86-avx2/`](bench/linux-x86-avx2/) and [`bench/linux-x86-scalar/`](bench/linux-x86-scalar/). They measure named command lines on one Linux x86-64 host; they do not describe every library or operating system.
