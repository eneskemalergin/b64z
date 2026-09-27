"""Generate the local Base64 fixture and benchmark data."""

from __future__ import annotations

import argparse
import base64
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
FIXTURE_ROOT = DATA_ROOT / "fixture"
BENCH_ROOT = DATA_ROOT / "bench"

BENCH_SIZES = {
    "tiny": 256,
    "small": 16 * 1024,
    "medium": 1024 * 1024,
    "large": 8 * 1024 * 1024,
    "huge": 32 * 1024 * 1024,
}

INVALID_CASES = {
    "invalid-character": (b"YQ@=", "InvalidCharacter"),
    "whitespace": (b"YQ==\n", "InvalidPadding"),
    "missing-padding": (b"YQ", "InvalidPadding"),
    "single-character": (b"Y", "InvalidPadding"),
    "misplaced-padding": (b"=AAA", "InvalidPadding"),
    "too-much-padding": (b"Y===", "InvalidPadding"),
    "nonzero-tail-one": (b"YR==", "InvalidPadding"),
    "nonzero-tail-two": (b"YWJ=", "InvalidPadding"),
    "internal-padding": (b"Y=Q=", "InvalidPadding"),
    "url-safe-alphabet": (b"-_==", "InvalidCharacter"),
    "avx2-character-before-padding": (
        b"AAAA@" + b"A" * 95 + b"=" + b"A" * 31,
        "InvalidCharacter",
    ),
    "avx2-padding-before-character": (
        b"AAAA=" + b"A" * 95 + b"@" + b"A" * 31,
        "InvalidPadding",
    ),
}


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def general_bytes(length: int, seed: int) -> bytes:
    """Return deterministic bytes with short repeated and changing regions."""

    output = bytearray(length)
    value = seed & 0xFFFFFFFF
    for index in range(length):
        value = (1664525 * value + 1013904223) & 0xFFFFFFFF
        byte = (value >> 24) & 0xFF
        if index % 257 == 0:
            byte = index & 0xFF
        elif index % 1021 == 0:
            byte = 0
        output[index] = byte
    return bytes(output)


def mzml_bytes(length: int, precision: int) -> bytes:
    """Return little-endian float payload bytes used by mzML binary arrays."""

    output = bytearray(length)
    width = precision // 8
    format_code = "<f" if precision == 32 else "<d"
    for index in range(0, length, width):
        point = index // width
        value = 100.0 + (point % 100000) * 0.01
        if point % 17 == 0:
            value = 0.0
        elif point % 29 == 0:
            value = float("inf")
        struct.pack_into(format_code, output, index, value)
    return bytes(output)


def valid_inputs() -> dict[str, bytes]:
    return {
        "empty": b"",
        "one-byte-zero": b"\x00",
        "one-byte-high": b"\xff",
        "two-bytes": b"\xff\x00",
        "three-bytes": b"\xff\x00\xaa",
        "four-bytes": b"\x00\xff\x10\xef",
        "control-bytes": b"\x00\n\r\t\x1b\x7f\x80\xfe\xff",
        "ascii-text": b"The quick brown fox jumps over the lazy dog.\n",
        "utf8-bytes": "Base64 is byte oriented: cafe\u0301 \u2603\n".encode(),
        "all-byte-values": bytes(range(256)),
        "boundary-63": general_bytes(63, 0x63),
        "boundary-64": general_bytes(64, 0x64),
        "boundary-65": general_bytes(65, 0x65),
        "boundary-1024": general_bytes(1024, 0x1024),
    }


def generate_fixtures() -> None:
    for name, raw in valid_inputs().items():
        write_bytes(FIXTURE_ROOT / "valid" / f"{name}.bin", raw)
        write_bytes(FIXTURE_ROOT / "valid" / f"{name}.b64", base64.b64encode(raw))

    for name, (encoded, error_name) in INVALID_CASES.items():
        write_bytes(FIXTURE_ROOT / "invalid" / f"{name}.b64", encoded)
        write_bytes(FIXTURE_ROOT / "invalid" / f"{name}.error", f"{error_name}\n".encode())


def generate_benchmarks() -> None:
    for index, (name, size) in enumerate(BENCH_SIZES.items(), start=1):
        general = general_bytes(size, 0xB64 + index)
        write_bytes(BENCH_ROOT / "general" / f"{name}.bin", general)
        for precision in (32, 64):
            mzml = mzml_bytes(size, precision)
            precision_root = BENCH_ROOT / "mzml" / f"float{precision}"
            write_bytes(precision_root / f"{name}.raw.bin", mzml)
            write_bytes(precision_root / f"{name}.zlib.bin", zlib.compress(mzml, level=6))


def write_data_notes() -> None:
    notes = """Generated Base64 data cases

Run `python3 tools/base64_data.py generate` to recreate these files.

`fixture/valid/` contains raw `.bin` inputs and exact unwrapped `.b64` outputs. `fixture/invalid/` contains encoded inputs and the expected B64Z error name in the matching `.error` file.

`bench/general/` contains deterministic byte streams. `bench/mzml/` contains generated 32-bit and 64-bit little-endian float arrays and their zlib-compressed forms, before Base64 conversion. They are not complete XML documents or measured instrument data.

The nominal sizes are tiny = 256 B, small = 16 KiB, medium = 1 MiB, large = 8 MiB, and huge = 32 MiB. For zlib files, the size names describe the array before compression.
"""
    write_bytes(DATA_ROOT / "README.txt", notes.encode())


def generate() -> None:
    generate_fixtures()
    generate_benchmarks()
    write_data_notes()
    print(f"generated local data under {DATA_ROOT}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("generate", help="create fixtures and benchmark inputs")
    return parser.parse_args()


def main() -> int:
    parse_args()
    generate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
