"""Check local peer executables against the valid and benchmark byte sets."""

from __future__ import annotations

import argparse
import filecmp
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_ROOT = ROOT / "tools" / "bin"
FIXTURE_ROOT = ROOT / "data" / "fixture"
BENCH_ROOT = ROOT / "data" / "bench"
CUSTOM_BINARY = ROOT / "zig-out" / "bin" / "custom-base64"

PEERS = (
    "aklomp-base64",
    "simdutf-fastbase64",
    "coreutils-base64",
    "turbo-base64",
    "rust-base64-simd",
    "rust-base64-simd-crate",
    "zig-std-base64",
)


def peer_command(peer: str, input_path: Path, decode: bool) -> list[str]:
    command = [str(BIN_ROOT / peer)]
    if peer == "aklomp-base64":
        command += ["--decode", "--no-strip-newlines"] if decode else ["--wrap=0"]
    elif peer == "simdutf-fastbase64":
        if decode:
            command.append("--decode")
    elif peer == "coreutils-base64":
        command += ["--decode"] if decode else ["-w", "0"]
    elif peer == "turbo-base64" or peer in {
        "rust-base64-simd",
        "rust-base64-simd-crate",
        "zig-std-base64",
    }:
        if decode:
            command.append("--decode")
    else:
        raise RuntimeError(f"unknown peer: {peer}")
    command.append(str(input_path))
    return command


def reference_command(reference: Path, input_path: Path) -> list[str]:
    return [str(reference), "--wrap=0", str(input_path)]


def custom_command(input_path: Path) -> list[str]:
    return [
        str(CUSTOM_BINARY),
        "--mode",
        "encode-memory",
        "--raw",
        str(input_path),
    ]


def run_to_file(command: list[str], output_path: Path) -> None:
    with output_path.open("wb") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{message}")


def compare_files(actual: Path, expected: Path, command: list[str]) -> None:
    if not filecmp.cmp(actual, expected, shallow=False):
        raise RuntimeError(
            f"byte mismatch for {' '.join(command)}\nactual={actual}\nexpected={expected}"
        )


def require_binaries(peers: list[str]) -> None:
    for peer in peers:
        binary = BIN_ROOT / peer
        if not binary.is_file():
            raise RuntimeError(f"missing peer executable: {binary}")


def verify_inputs(peers: list[str], inputs: list[Path], temporary: Path) -> int:
    checked = 0
    for input_path in inputs:
        expected_encoded = input_path.with_suffix(".b64")
        for peer in peers:
            encoded = temporary / f"{peer}-{checked}.b64"
            command = peer_command(peer, input_path, decode=False)
            run_to_file(command, encoded)
            compare_files(encoded, expected_encoded, command)

            decoded = temporary / f"{peer}-{checked}.bin"
            command = peer_command(peer, expected_encoded, decode=True)
            run_to_file(command, decoded)
            compare_files(decoded, input_path, command)
        checked += 1
    return checked


def verify_benchmarks(
    peers: list[str], reference: Path | None, temporary: Path
) -> int:
    if reference is None and not CUSTOM_BINARY.is_file():
        raise RuntimeError(
            f"missing B64Z executable: {CUSTOM_BINARY}; build it or pass --reference"
        )
    if reference is not None and not reference.is_file():
        raise RuntimeError(f"missing reference executable: {reference}")

    checked = 0
    for input_path in sorted(BENCH_ROOT.rglob("*.bin")):
        expected_encoded = temporary / f"reference-{checked}.b64"
        if reference is None:
            run_to_file(custom_command(input_path), expected_encoded)
        else:
            run_to_file(reference_command(reference, input_path), expected_encoded)

        for peer in peers:
            encoded = temporary / f"bench-{peer}-{checked}.b64"
            command = peer_command(peer, input_path, decode=False)
            run_to_file(command, encoded)
            compare_files(encoded, expected_encoded, command)

            decoded = temporary / f"bench-{peer}-{checked}.bin"
            command = peer_command(peer, expected_encoded, decode=True)
            run_to_file(command, decoded)
            compare_files(decoded, input_path, command)
        checked += 1
    return checked


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", action="store_true", help="also check all benchmark inputs")
    parser.add_argument(
        "--peer",
        action="append",
        choices=PEERS,
        help="check one peer; repeat the option to select several peers",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        help="use an Aklomp-compatible executable for benchmark encodings",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    peers = arguments.peer or list(PEERS)
    require_binaries(peers)
    valid_inputs = sorted((FIXTURE_ROOT / "valid").glob("*.bin"))
    if not valid_inputs:
        raise RuntimeError(f"no valid fixtures found under {FIXTURE_ROOT / 'valid'}")

    with tempfile.TemporaryDirectory(prefix="b64z-peers-") as temporary_name:
        temporary = Path(temporary_name)
        valid_count = verify_inputs(peers, valid_inputs, temporary)
        bench_count = (
            verify_benchmarks(peers, arguments.reference.resolve() if arguments.reference else None, temporary)
            if arguments.bench
            else 0
        )
    print(
        f"verified {valid_count} valid fixture pairs and {bench_count} benchmark inputs "
        f"across {len(peers)} peers"
    )
    return 0


try:
    raise SystemExit(main())
except (OSError, RuntimeError) as error:
    print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1)
