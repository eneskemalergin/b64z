"""Generate and verify the local Base64 fixture and benchmark data."""

from __future__ import annotations

import argparse
import base64
import filecmp
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
FIXTURE_ROOT = DATA_ROOT / "fixture"
BENCH_ROOT = DATA_ROOT / "bench"
CACHE_ROOT = DATA_ROOT / ".verified"
CACHE_PATH = CACHE_ROOT / "reference.cache"
CUSTOM_BINARY = ROOT / "zig-out" / "bin" / "custom-base64"

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
    notes = """Local Base64 data cases

This directory is ignored by design. Run `python3 tools/base64_data.py generate`
to recreate it.

`fixture/valid/` contains raw `.bin` inputs and exact unwrapped `.b64` outputs.
`fixture/invalid/` contains encoded inputs and the expected B64Z error name in
the matching `.error` file.

`bench/general/` contains ordinary deterministic byte streams. `bench/mzml/`
contains 32-bit and 64-bit little-endian float payloads and their zlib-compressed
forms. The payloads are the bytes that an mzML `<binary>` element carries after
optional zlib compression. They are not complete XML documents.

The five benchmark sizes are 256 B, 16 KiB, 1 MiB, 8 MiB, and 32 MiB.
"""
    write_bytes(DATA_ROOT / "README.txt", notes.encode())


def generate() -> None:
    generate_fixtures()
    generate_benchmarks()
    write_data_notes()
    print(f"generated local data under {DATA_ROOT}")


def run_to_file(command: list[str], output_path: Path) -> subprocess.CompletedProcess[bytes]:
    with output_path.open("wb") as output:
        return subprocess.run(
            command, stdout=output, stderr=subprocess.PIPE, text=False, check=False
        )


def compare_files(left: Path, right: Path) -> None:
    if not filecmp.cmp(left, right, shallow=False):
        raise RuntimeError(f"byte mismatch: {left} != {right}")


def custom_command(mode: str, input_path: Path, chunk: int, raw: bool = True) -> list[str]:
    command = [str(CUSTOM_BINARY), "--mode", mode, "--chunk", str(chunk)]
    if raw:
        command.append("--raw")
    command.append(str(input_path))
    return command


def reference_command(reference: Path, input_path: Path, decode: bool) -> list[str]:
    command = [str(reference)]
    if decode:
        command.extend(["--decode", "--no-strip-newlines"])
    else:
        command.extend(["--wrap=0"])
    command.append(str(input_path))
    return command


def require_success(result: subprocess.CompletedProcess[bytes], command: list[str]) -> None:
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{error}")


def verify_cli_names() -> None:
    input_path = FIXTURE_ROOT / "valid" / "one-byte-zero.bin"
    for removed_name in ("encode-one-shot", "decode-one-shot"):
        command = [str(CUSTOM_BINARY), "--mode", removed_name, "--raw", str(input_path)]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode == 0:
            raise RuntimeError(f"removed CLI mode was accepted: {removed_name}")


def verify_fixture_valid(reference: Path | None, temporary: Path) -> int:
    count = 0
    for raw_path in sorted((FIXTURE_ROOT / "valid").glob("*.bin")):
        expected_path = raw_path.with_suffix(".b64")
        custom_encoded = temporary / f"custom-{raw_path.stem}.b64"
        result = run_to_file(custom_command("encode-memory", raw_path, 64), custom_encoded)
        require_success(result, custom_command("encode-memory", raw_path, 64))
        compare_files(custom_encoded, expected_path)

        streamed_encoded = temporary / f"stream-{raw_path.stem}.b64"
        command = custom_command("encode-streaming", raw_path, 7)
        result = run_to_file(command, streamed_encoded)
        require_success(result, command)
        compare_files(streamed_encoded, expected_path)

        custom_decoded = temporary / f"custom-{raw_path.stem}.bin"
        command = custom_command("decode-memory", expected_path, 64)
        result = run_to_file(command, custom_decoded)
        require_success(result, command)
        compare_files(custom_decoded, raw_path)

        streamed_decoded = temporary / f"stream-{raw_path.stem}.bin"
        command = custom_command("decode-streaming", expected_path, 5)
        result = run_to_file(command, streamed_decoded)
        require_success(result, command)
        compare_files(streamed_decoded, raw_path)

        if reference is not None:
            reference_encoded = temporary / f"reference-{raw_path.stem}.b64"
            command = reference_command(reference, raw_path, decode=False)
            result = run_to_file(command, reference_encoded)
            require_success(result, command)
            compare_files(reference_encoded, expected_path)

            reference_decoded = temporary / f"reference-{raw_path.stem}.bin"
            command = reference_command(reference, expected_path, decode=True)
            result = run_to_file(command, reference_decoded)
            require_success(result, command)
            compare_files(reference_decoded, raw_path)
        count += 1
    return count


def verify_fixture_invalid(reference: Path | None, temporary: Path) -> tuple[int, int]:
    count = 0
    reference_rejected = 0
    for encoded_path in sorted((FIXTURE_ROOT / "invalid").glob("*.b64")):
        expected_error = encoded_path.with_suffix(".error").read_text().strip()
        output_path = temporary / f"invalid-{encoded_path.stem}.bin"
        command = custom_command("decode-memory", encoded_path, 64)
        result = run_to_file(command, output_path)
        if result.returncode == 0:
            raise RuntimeError(f"invalid input was accepted: {encoded_path}")
        error = result.stderr.decode(errors="replace")
        if expected_error not in error:
            raise RuntimeError(
                f"wrong error for {encoded_path}: expected {expected_error}, got {error.strip()}"
            )

        if reference is not None:
            command = reference_command(reference, encoded_path, decode=True)
            result = subprocess.run(command, capture_output=True, check=False)
            if result.returncode != 0:
                reference_rejected += 1
        count += 1
    return count, reference_rejected


def benchmark_inputs() -> list[Path]:
    return sorted(BENCH_ROOT.rglob("*.bin"))


def cache_header(reference: Path) -> str:
    stat = reference.stat()
    return f"# reference={reference} size={stat.st_size} mtime_ns={stat.st_mtime_ns}\n"


def read_cache(reference: Path | None) -> dict[str, tuple[int, int, int]]:
    if not CACHE_PATH.exists():
        return {}
    lines = CACHE_PATH.read_text().splitlines()
    if not lines or lines[0] != "# b64z reference cache v2":
        return {}
    if reference is not None:
        expected_header = cache_header(reference).rstrip("\n")
        if len(lines) < 2 or lines[1] != expected_header:
            return {}

    records: dict[str, tuple[int, int, int]] = {}
    for line in lines[2:]:
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        path_name, size, mtime_ns, encoded_size = fields
        try:
            parsed_size = int(size)
            parsed_mtime_ns = int(mtime_ns)
            parsed_encoded_size = int(encoded_size)
        except ValueError:
            continue
        if not path_name or parsed_size < 0 or parsed_encoded_size < 0:
            continue
        records[path_name] = (parsed_size, parsed_mtime_ns, parsed_encoded_size)
    return records


def write_cache(reference: Path, records: dict[str, tuple[int, int, int]]) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    lines = ["# b64z reference cache v2", cache_header(reference).rstrip("\n")]
    for path_name in sorted(records):
        size, mtime_ns, encoded_size = records[path_name]
        lines.append(f"{path_name}\t{size}\t{mtime_ns}\t{encoded_size}")
    CACHE_PATH.write_text("\n".join(lines) + "\n")


def qualify_benchmarks(reference: Path, temporary: Path) -> dict[str, tuple[int, int, int]]:
    records: dict[str, tuple[int, int, int]] = {}
    for input_path in benchmark_inputs():
        relative = input_path.relative_to(DATA_ROOT).as_posix()
        reference_encoded = temporary / f"reference-{len(records)}.b64"
        command = reference_command(reference, input_path, decode=False)
        result = run_to_file(command, reference_encoded)
        require_success(result, command)

        custom_encoded = temporary / f"custom-{len(records)}.b64"
        command = custom_command("encode-streaming", input_path, 8191)
        result = run_to_file(command, custom_encoded)
        require_success(result, command)
        compare_files(reference_encoded, custom_encoded)

        custom_decoded = temporary / f"decoded-{len(records)}.bin"
        command = custom_command("decode-streaming", reference_encoded, 4093)
        result = run_to_file(command, custom_decoded)
        require_success(result, command)
        compare_files(custom_decoded, input_path)

        stat = input_path.stat()
        records[relative] = (stat.st_size, stat.st_mtime_ns, reference_encoded.stat().st_size)
    return records


def verify_cached_benchmarks(records: dict[str, tuple[int, int, int]], temporary: Path) -> int:
    count = 0
    for input_path in benchmark_inputs():
        relative = input_path.relative_to(DATA_ROOT).as_posix()
        record = records.get(relative)
        if record is None:
            raise RuntimeError(f"no reference cache entry for {relative}; run with --reference")
        size, mtime_ns, expected_encoded_size = record
        stat = input_path.stat()
        if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
            raise RuntimeError(f"reference cache is stale for {relative}; run with --reference")

        encoded = temporary / f"cached-{count}.b64"
        command = custom_command("encode-streaming", input_path, 8191)
        result = run_to_file(command, encoded)
        require_success(result, command)
        if encoded.stat().st_size != expected_encoded_size:
            raise RuntimeError(f"encoded length changed for {relative}")

        decoded = temporary / f"cached-{count}.bin"
        command = custom_command("decode-streaming", encoded, 4093)
        result = run_to_file(command, decoded)
        require_success(result, command)
        compare_files(decoded, input_path)
        count += 1
    return count


def verify(reference: Path | None) -> None:
    if not CUSTOM_BINARY.exists():
        raise RuntimeError(f"missing custom binary: {CUSTOM_BINARY}; run zig build first")
    if reference is not None and not reference.exists():
        raise RuntimeError(f"missing reference binary: {reference}")

    with tempfile.TemporaryDirectory(prefix="b64z-verify-") as temporary_name:
        temporary = Path(temporary_name)
        verify_cli_names()
        valid_count = verify_fixture_valid(reference, temporary)
        invalid_count, rejected_count = verify_fixture_invalid(reference, temporary)
        records = read_cache(reference)
        if reference is not None:
            records = qualify_benchmarks(reference, temporary)
            write_cache(reference, records)
        bench_count = verify_cached_benchmarks(records, temporary)

    if reference is not None:
        print(
            f"verified {valid_count} valid fixtures, {invalid_count} invalid fixtures, "
            f"and {bench_count} benchmark inputs with Aklomp; "
            f"Aklomp rejected {rejected_count} invalid fixtures"
        )
    else:
        print(
            f"verified {valid_count} valid fixtures, {invalid_count} invalid fixtures, "
            f"and {bench_count} benchmark inputs from the local cache; "
            "external invalid-input results were not checked"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("generate", help="create fixtures and benchmark inputs")
    verify_parser = subcommands.add_parser("verify", help="check fixtures and cached benchmark data")
    verify_parser.add_argument(
        "--reference",
        type=Path,
        help="Aklomp base64 executable; qualification refreshes the local cache",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    if arguments.command == "generate":
        generate()
        return 0

    reference = arguments.reference
    if reference is None and os.environ.get("AKLOMP_BASE64"):
        reference = Path(os.environ["AKLOMP_BASE64"])
    if reference is not None:
        reference = reference.resolve()
    try:
        verify(reference)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
