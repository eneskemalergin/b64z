# B64Z

B64Z is a strict RFC 4648 Base64 codec with caller-owned output buffers, memory and stateful streaming APIs, and an AVX2 fast path on x86-64.

The public library is in [`src/base64.zig`](src/base64.zig). It exposes `encodedSize`, `decodedSize`, `encode`, `decode`, `encodeInPlace`, `decodeInPlace`, `Encoder`, and `Decoder`. The normal functions do not allocate and reject short or overlapping output buffers. Decode rejects invalid alphabet bytes, whitespace, misplaced padding, and non-zero discarded tail bits.

The command-line adapter is [`src/main.zig`](src/main.zig). It supports the same memory and chunked streaming operations and uses bounded buffers for streaming input and output.

## Checks

Use Zig 0.16:

```sh
zig build test --summary all
zig build test -Dcpu=native -Doptimize=ReleaseFast --summary all
zig build -Dcpu=native -Doptimize=ReleaseFast -Dstrip=true --summary all
```

Local fixture and benchmark data is generated under the ignored `data/` directory. Use the Aklomp executable to refresh the byte-qualification cache:

```sh
python3 tools/base64_data.py generate
python3 tools/base64_data.py verify --reference /path/to/base64
```

## Peer checks

The locally built peer tools are checked with direct file arguments and byte comparisons:

```sh
python3 tools/peer_check.py
python3 tools/peer_check.py --bench --reference tools/bin/aklomp-base64
```

These commands qualify output bytes. They do not claim a speed ranking. A timing runner is not present in this checkout yet.
