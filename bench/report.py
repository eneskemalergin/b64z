#!/usr/bin/env python3
"""Verify, measure, and render the two retained B64Z benchmark reports."""

from __future__ import annotations

import argparse
import csv
import filecmp
import json
import math
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "bench"
DATA_ROOT = ROOT / "data"
BENCH_DATA_ROOT = DATA_ROOT / "bench"
FIXTURE_ROOT = DATA_ROOT / "fixture"
WORK_ROOT = BENCH_ROOT / "work"
REFERENCE_BINARY = ROOT / "tools" / "bin" / "aklomp-base64"
REFERENCE_CACHE = WORK_ROOT / "inputs" / "reference.cache"

MODES = (
    "encode-memory",
    "encode-streaming",
    "decode-memory",
    "decode-streaming",
)
SIZE_NAMES = ("tiny", "small", "medium", "large", "huge")
CHUNKS = {
    "encode-memory": 65536,
    "decode-memory": 65536,
    "encode-streaming": 8191,
    "decode-streaming": 4093,
}
DEFAULT_RUNS = 20
DEFAULT_WARMUP = 5
DEFAULT_DURATION_MS = 15000

COLORS = {
    "b64z": "#F59E0B",
    "aklomp": "#2563EB",
    "coreutils": "#6B7280",
    "simdutf": "#0F766E",
    "turbo": "#A16207",
    "rust-base64": "#64748B",
    "rust-simd": "#0EA5A4",
    "zig-std": "#94A3B8",
}
MARKERS = {
    "b64z": 7,
    "aklomp": 5,
    "coreutils": 4,
    "simdutf": 9,
    "turbo": 13,
    "rust-base64": 8,
    "rust-simd": 10,
    "zig-std": 6,
}
GNUPLOT_PLOT_SEPARATOR = ", " + chr(92) + "\n    "


class BenchmarkError(RuntimeError):
    """The benchmark cannot produce a complete report."""


@dataclass(frozen=True)
class Target:
    id: str
    cpu: str
    backend: str

    @property
    def directory(self) -> Path:
        return BENCH_ROOT / self.id

    @property
    def binary(self) -> Path:
        return self.directory / "bin" / "custom-base64"


TARGETS = {
    "linux-x86-avx2": Target("linux-x86-avx2", "haswell", "avx2"),
    "linux-x86-scalar": Target("linux-x86-scalar", "x86_64", "scalar"),
}


@dataclass(frozen=True)
class Peer:
    id: str
    label: str
    executable: Path
    version: str
    encode_args: tuple[str, ...]
    decode_args: tuple[str, ...]
    modes: tuple[str, ...]


PEERS = (
    Peer(
        "aklomp",
        "Aklomp",
        ROOT / "tools/bin/aklomp-base64",
        "aklomp/base64 bf058e571ac5002b75b03fed38e33ed4e8d45eff, upstream make",
        ("--wrap=0",),
        ("--decode", "--no-strip-newlines"),
        ("encode-streaming", "decode-streaming"),
    ),
    Peer(
        "simdutf",
        "simdutf",
        ROOT / "tools/bin/simdutf-fastbase64",
        "simdutf v9.2.0 8abc1d7a466bc882c2d72e1effd8661492db257c, Release CMake and direct C++ adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "coreutils",
        "GNU coreutils",
        ROOT / "tools/bin/coreutils-base64",
        "GNU coreutils base64 9.11, local build flags -g -O2",
        ("-w", "0"),
        ("--decode",),
        ("encode-streaming", "decode-streaming"),
    ),
    Peer(
        "turbo",
        "Turbo-Base64",
        ROOT / "tools/bin/turbo-base64",
        "Turbo-Base64 d9e584363280055ba6355938a48dc3711183f50f, upstream make and direct C adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "rust-base64",
        "Rust base64",
        ROOT / "tools/bin/rust-base64-simd",
        "Rust base64 crate 0.23.1, Simd engine, Cargo release fat LTO",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "rust-simd",
        "Rust base64-simd",
        ROOT / "tools/bin/rust-base64-simd-crate",
        "Rust base64-simd crate 0.8.0, Cargo release fat LTO",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "zig-std",
        "Zig std.base64",
        ROOT / "tools/bin/zig-std-base64",
        "Zig 0.16.0 std.base64, ReleaseFast -Dcpu=native adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
)
PEER_BY_ID = {peer.id: peer for peer in PEERS}


@dataclass(frozen=True)
class Case:
    id: str
    label: str
    family: str
    variant: str
    size: str
    raw_path: Path
    encoded_path: Path

    @property
    def raw_bytes(self) -> int:
        return self.raw_path.stat().st_size

    @property
    def encoded_bytes(self) -> int:
        return self.encoded_path.stat().st_size


@dataclass(frozen=True)
class Measurement:
    mode: str
    case_id: str
    case_label: str
    family: str
    variant: str
    size: str
    tool: str
    input_bytes: int
    output_bytes: int
    wall_ns: float
    wall_std_ns: float
    wall_q1_ns: float
    wall_median_ns: float
    wall_q3_ns: float
    rss_bytes: float
    rss_q1_bytes: float
    rss_median_bytes: float
    rss_q3_bytes: float
    samples: int
    failed_samples: int
    command: str


MEASUREMENT_COLUMNS = (
    "mode",
    "case_id",
    "case_label",
    "family",
    "variant",
    "size",
    "tool",
    "input_bytes",
    "output_bytes",
    "wall_ns",
    "wall_std_ns",
    "wall_q1_ns",
    "wall_median_ns",
    "wall_q3_ns",
    "rss_bytes",
    "rss_q1_bytes",
    "rss_median_bytes",
    "rss_q3_bytes",
    "samples",
    "failed_samples",
    "command",
)
SUMMARY_COLUMNS = (
    "mode",
    "tool",
    "cases",
    "time_ratio",
    "rss_ratio",
    "time_iqr_low",
    "time_iqr_high",
    "rss_iqr_low",
    "rss_iqr_high",
    "faster_than_b64z",
    "lower_rss_than_b64z",
    "huge_time_ms",
    "huge_rss_mib",
)


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def expected_encoded_size(size: int) -> int:
    return ((size + 2) // 3) * 4


def discover_cases() -> tuple[Case, ...]:
    if not BENCH_DATA_ROOT.is_dir():
        raise BenchmarkError(f"missing benchmark data directory: {BENCH_DATA_ROOT}")
    cases: list[Case] = []
    for raw_path in sorted(BENCH_DATA_ROOT.rglob("*.bin")):
        rel = raw_path.relative_to(BENCH_DATA_ROOT)
        if rel.parts[0] == "general" and len(rel.parts) == 2:
            size = raw_path.name.removesuffix(".bin")
            case_id = f"general-{size}"
            label = f"general / {size}"
            family = "general"
            variant = "general"
        elif rel.parts[0] == "mzml" and len(rel.parts) == 3:
            size = raw_path.name.removesuffix(".raw.bin").removesuffix(".zlib.bin")
            precision = rel.parts[1].removeprefix("float")
            variant = "raw" if raw_path.name.endswith(".raw.bin") else "zlib"
            family = f"mzML float{precision}"
            case_id = f"mzml-float{precision}-{size}-{variant}"
            label = f"mzML float{precision} / {size} {variant}"
        else:
            raise BenchmarkError(f"unrecognized benchmark input path: {raw_path}")
        encoded_path = WORK_ROOT / "inputs" / "encoded" / rel.parent / (
            raw_path.name.removesuffix(".bin") + ".b64"
        )
        cases.append(
            Case(case_id, label, family, variant, size, raw_path, encoded_path)
        )
    if len(cases) != 25:
        raise BenchmarkError(f"expected 25 benchmark inputs, found {len(cases)}")
    return tuple(cases)


def run_command(command: list[str], *, stdout: int | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=ROOT,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def error_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stderr.decode(errors="replace").strip()


def write_process_output(command: list[str], output_path: Path) -> subprocess.CompletedProcess[bytes]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        return run_command(command, stdout=output.fileno())


def require_files(target: Target) -> None:
    required = [target.binary, REFERENCE_BINARY, *(peer.executable for peer in PEERS)]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise BenchmarkError("missing executable(s): " + ", ".join(missing))


def current_encoded(case: Case) -> bool:
    try:
        raw_stat = case.raw_path.stat()
        encoded_stat = case.encoded_path.stat()
    except FileNotFoundError:
        return False
    return (
        encoded_stat.st_size == expected_encoded_size(raw_stat.st_size)
        and encoded_stat.st_mtime_ns >= raw_stat.st_mtime_ns
    )


def reference_signature() -> str:
    stat = REFERENCE_BINARY.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def current_reference_cache(cases: Iterable[Case]) -> bool:
    try:
        lines = REFERENCE_CACHE.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return False
    return (
        lines == [f"reference={reference_signature()}"]
        and all(current_encoded(case) for case in cases)
    )


def write_reference_cache() -> None:
    REFERENCE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = REFERENCE_CACHE.with_name(f".{REFERENCE_CACHE.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(f"reference={reference_signature()}\n", encoding="utf-8")
        temporary.replace(REFERENCE_CACHE)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_inputs(cases: Iterable[Case]) -> int:
    cases = tuple(cases)
    if current_reference_cache(cases):
        return 0

    generated = 0
    for case in cases:
        case.encoded_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = case.encoded_path.with_name(
            f".{case.encoded_path.name}.{os.getpid()}.tmp"
        )
        command = [str(REFERENCE_BINARY), "--wrap=0", str(case.raw_path)]
        try:
            result = write_process_output(command, temporary)
            if result.returncode != 0:
                raise BenchmarkError(
                    f"reference encode failed for {case.label}: {error_text(result)}"
                )
            if temporary.stat().st_size != expected_encoded_size(case.raw_bytes):
                raise BenchmarkError(f"reference output has the wrong size: {case.label}")
            temporary.replace(case.encoded_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        generated += 1
    write_reference_cache()
    return generated


def b64z_command(
    target: Target, mode: str, input_path: Path, chunk: int | None = None
) -> list[str]:
    selected_chunk = CHUNKS[mode] if chunk is None else chunk
    return [
        str(target.binary),
        "--mode",
        mode,
        "--chunk",
        str(selected_chunk),
        "--raw",
        str(input_path),
    ]


def peer_command(peer: Peer, mode: str, input_path: Path) -> list[str]:
    args = peer.decode_args if mode.startswith("decode-") else peer.encode_args
    return [str(peer.executable), *args, str(input_path)]


def command_text(command: list[str]) -> str:
    display = []
    for token in command:
        if token.startswith(str(ROOT)):
            display.append(relative(Path(token)))
        else:
            display.append(token)
    return shlex.join(display)


def public_command_text(tool: str, mode: str) -> str:
    if tool == "b64z":
        return shlex.join(
            [
                "B64Z",
                "--mode",
                mode,
                "--chunk",
                str(CHUNKS[mode]),
                "--raw",
                "INPUT",
            ]
        )
    peer = PEER_BY_ID[tool]
    args = peer.decode_args if mode.startswith("decode-") else peer.encode_args
    return shlex.join([tool, *args, "INPUT"])


def compare_output(
    command: list[str], expected: Path, output: Path, description: str
) -> None:
    result = write_process_output(command, output)
    if result.returncode != 0:
        raise BenchmarkError(f"{description} failed: {error_text(result)}")
    if not filecmp.cmp(output, expected, shallow=False):
        raise BenchmarkError(
            f"byte mismatch for {description}: {command_text(command)}"
        )


def verify(target: Target, cases: tuple[Case, ...]) -> str:
    valid = sorted((FIXTURE_ROOT / "valid").glob("*.bin"))
    invalid = sorted((FIXTURE_ROOT / "invalid").glob("*.b64"))
    if not valid or not invalid:
        raise BenchmarkError("fixture directories are missing valid or invalid cases")
    target_checks = 0
    peer_checks = 0
    reference_checks = 0
    invalid_checks = 0
    with tempfile.TemporaryDirectory(prefix="b64z-verify-") as directory:
        temporary = Path(directory)
        for raw_path in valid:
            encoded_path = raw_path.with_suffix(".b64")
            for mode, chunk in (("encode-memory", 64), ("encode-streaming", 7)):
                compare_output(
                    b64z_command(target, mode, raw_path, chunk),
                    encoded_path,
                    temporary / f"target-{raw_path.stem}-{mode}.b64",
                    f"B64Z {mode} fixture {raw_path.name}",
                )
                target_checks += 1
            for mode, chunk in (("decode-memory", 64), ("decode-streaming", 5)):
                compare_output(
                    b64z_command(target, mode, encoded_path, chunk),
                    raw_path,
                    temporary / f"target-{raw_path.stem}-{mode}.bin",
                    f"B64Z {mode} fixture {raw_path.name}",
                )
                target_checks += 1
            compare_output(
                [str(REFERENCE_BINARY), "--wrap=0", str(raw_path)],
                encoded_path,
                temporary / f"reference-{raw_path.stem}.b64",
                f"Aklomp encode fixture {raw_path.name}",
            )
            compare_output(
                [str(REFERENCE_BINARY), "--decode", "--no-strip-newlines", str(encoded_path)],
                raw_path,
                temporary / f"reference-{raw_path.stem}.bin",
                f"Aklomp decode fixture {raw_path.name}",
            )
            reference_checks += 2

        for encoded_path in invalid:
            expected_error = encoded_path.with_suffix(".error").read_text(encoding="utf-8").strip()
            for mode, chunk in (("decode-memory", 64), ("decode-streaming", 5)):
                output = temporary / f"target-invalid-{encoded_path.stem}-{mode}.bin"
                result = write_process_output(
                    b64z_command(target, mode, encoded_path, chunk), output
                )
                if result.returncode == 0:
                    raise BenchmarkError(
                        f"B64Z accepted invalid fixture {encoded_path.name} in {mode}"
                    )
                if expected_error not in error_text(result):
                    raise BenchmarkError(
                        f"wrong B64Z error for {encoded_path.name} in {mode}: "
                        f"expected {expected_error}, got {error_text(result)}"
                    )
                invalid_checks += 1

        for case in cases:
            for mode in ("encode-memory", "encode-streaming"):
                compare_output(
                    b64z_command(target, mode, case.raw_path),
                    case.encoded_path,
                    temporary / f"target-{case.id}-{mode}.b64",
                    f"B64Z {mode} {case.label}",
                )
                target_checks += 1
            for mode in ("decode-memory", "decode-streaming"):
                compare_output(
                    b64z_command(target, mode, case.encoded_path),
                    case.raw_path,
                    temporary / f"target-{case.id}-{mode}.bin",
                    f"B64Z {mode} {case.label}",
                )
                target_checks += 1

        for peer in PEERS:
            operations = {
                "encode-memory" if mode.startswith("encode-") else "decode-memory"
                for mode in peer.modes
            }
            for raw_path in valid:
                encoded_path = raw_path.with_suffix(".b64")
                for operation in sorted(operations):
                    input_path = raw_path if operation.startswith("encode-") else encoded_path
                    expected = encoded_path if operation.startswith("encode-") else raw_path
                    compare_output(
                        peer_command(peer, operation, input_path),
                        expected,
                        temporary / f"{peer.id}-fixture-{raw_path.stem}-{operation}",
                        f"{peer.label} {operation} fixture {raw_path.name}",
                    )
                    peer_checks += 1
            for case in cases:
                for operation in sorted(operations):
                    input_path = case.raw_path if operation.startswith("encode-") else case.encoded_path
                    expected = case.encoded_path if operation.startswith("encode-") else case.raw_path
                    compare_output(
                        peer_command(peer, operation, input_path),
                        expected,
                        temporary / f"{peer.id}-{case.id}-{operation}",
                        f"{peer.label} {operation} {case.label}",
                    )
                    peer_checks += 1
    return (
        f"target byte checks={target_checks}, invalid checks={invalid_checks}, "
        f"Aklomp reference checks={reference_checks}, peer byte checks={peer_checks}"
    )


def zebrac_path() -> Path:
    configured = os.environ.get("ZEBRAC")
    candidates = [Path(configured)] if configured else []
    found = shutil.which("zebrac")
    if found:
        candidates.append(Path(found))
    candidates.append(Path("/home/eke/bin/zebrac"))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise BenchmarkError("cannot find zebrac; set ZEBRAC to its executable")


def version_text(command: list[str]) -> str:
    result = run_command(command)
    if result.returncode != 0:
        return "unknown"
    return result.stdout.decode(errors="replace").strip().splitlines()[0]


def git_value(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.decode(errors="replace").strip() if result.returncode == 0 else "unknown"


def git_has_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def environment_metadata(
    target: Target,
    zebrac: Path,
    generated_utc: str,
    preparation: str,
    verification: str,
) -> dict[str, str]:
    model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    governor_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    try:
        governor = governor_path.read_text(encoding="utf-8").strip()
    except OSError:
        governor = "unknown"
    return {
        "generated_utc": generated_utc,
        "target": target.id,
        "build_cpu": target.cpu,
        "b64z_version": version_text([str(target.binary), "--version"]),
        "zig_version": version_text(["zig", "version"]),
        "zebrac_version": version_text([str(zebrac), "--version"]),
        "gnuplot_version": version_text(["gnuplot", "--version"]),
        "gcc_version": version_text(["gcc", "--version"]),
        "clang_version": version_text(["clang", "--version"]),
        "rustc_version": version_text(["rustc", "--version"]),
        "cargo_version": version_text(["cargo", "--version"]),
        "cmake_version": version_text(["cmake", "--version"]),
        "make_version": version_text(["make", "--version"]),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu_model": model,
        "cpu_count": str(os.cpu_count() or "unknown"),
        "cpu_governor": governor,
        "git_commit": git_value(["rev-parse", "HEAD"]),
        "git_changes": "yes" if git_has_changes() else "no",
        "input_preparation": preparation,
        "verification": verification,
    }


def run_zebrac(
    zebrac: Path,
    commands: list[str],
    output_path: Path,
    runs: int,
    warmup: int,
    duration_ms: int,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(zebrac),
        "--quiet",
        "--duration",
        str(duration_ms),
        "--min-samples",
        str(runs),
        "--max-samples",
        str(runs),
        "--warmup",
        str(warmup),
        "--json",
        str(output_path),
        "--",
        *commands,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BenchmarkError(
            f"zebrac failed for {commands[0]}: {result.stderr.strip()}"
        )
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BenchmarkError(f"cannot read zebrac output {output_path}: {error}") from error
    results = data.get("results")
    if not isinstance(results, list) or len(results) != len(commands):
        raise BenchmarkError(f"zebrac returned an incomplete result: {output_path}")
    for item in results:
        if item.get("sample_count") != runs or item.get("failed_sample_count") != 0:
            raise BenchmarkError(f"zebrac returned failed samples: {output_path}")
    return data


def metric(item: dict[str, object], name: str, field: str) -> float:
    values = item.get(name)
    if not isinstance(values, dict) or field not in values:
        raise BenchmarkError(f"zebrac result has no {name}.{field}")
    return float(values[field])


def to_measurement(
    mode: str, case: Case, tool: str, command: str, item: dict[str, object]
) -> Measurement:
    return Measurement(
        mode,
        case.id,
        case.label,
        case.family,
        case.variant,
        case.size,
        tool,
        case.raw_bytes if mode.startswith("encode-") else case.encoded_bytes,
        case.encoded_bytes if mode.startswith("encode-") else case.raw_bytes,
        metric(item, "wall_time", "mean"),
        metric(item, "wall_time", "std_dev"),
        metric(item, "wall_time", "q1"),
        metric(item, "wall_time", "median"),
        metric(item, "wall_time", "q3"),
        metric(item, "peak_rss", "mean"),
        metric(item, "peak_rss", "q1"),
        metric(item, "peak_rss", "median"),
        metric(item, "peak_rss", "q3"),
        int(item["sample_count"]),
        int(item["failed_sample_count"]),
        command,
    )


def control_gap(data: dict[str, object], metric_name: str) -> float:
    results = data["results"]
    left = metric(results[0], metric_name, "mean")
    right = metric(results[1], metric_name, "mean")
    return abs(left - right) / min(left, right) if min(left, right) > 0 else 0.0


def measure(
    target: Target,
    cases: tuple[Case, ...],
    runs: int,
    warmup: int,
    duration_ms: int,
    zebrac: Path,
) -> tuple[list[Measurement], dict[str, float]]:
    raw_root = WORK_ROOT / target.id / "raw"
    measurements: list[Measurement] = []
    total = len(MODES) * len(cases)
    completed = 0
    for mode in MODES:
        for case in cases:
            input_path = case.raw_path if mode.startswith("encode-") else case.encoded_path
            specs: list[tuple[str, list[str]]] = [("b64z", b64z_command(target, mode, input_path))]
            for peer in PEERS:
                if mode in peer.modes:
                    specs.append((peer.id, peer_command(peer, mode, input_path)))
            commands = [command_text(command) for _, command in specs]
            raw_path = raw_root / f"{mode}-{case.id}.json"
            data = run_zebrac(zebrac, commands, raw_path, runs, warmup, duration_ms)
            for (tool, command), item in zip(specs, data["results"], strict=True):
                measurements.append(
                    to_measurement(mode, case, tool, public_command_text(tool, mode), item)
                )
            completed += 1
            print(f"measured {completed}/{total} {mode} {case.id}")

    control_gaps: dict[str, float] = {}
    huge = next(case for case in cases if case.id == "general-huge")
    for mode in MODES:
        input_path = huge.raw_path if mode.startswith("encode-") else huge.encoded_path
        command = command_text(b64z_command(target, mode, input_path))
        raw_path = raw_root / f"control-{mode}.json"
        data = run_zebrac(zebrac, [command, command], raw_path, runs, warmup, duration_ms)
        control_gaps[f"control_{mode}_time_gap"] = control_gap(data, "wall_time")
        control_gaps[f"control_{mode}_rss_gap"] = control_gap(data, "peak_rss")
    return measurements, control_gaps


def fmt_number(value: float) -> str:
    return format(value, ".12g")


def write_measurements(
    path: Path,
    measurements: list[Measurement],
    metadata: dict[str, str],
    controls: dict[str, float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as output:
        for key, value in metadata.items():
            output.write(f"# {key}={value}\n")
        for key, value in controls.items():
            output.write(f"# {key}={fmt_number(value)}\n")
        writer = csv.DictWriter(
            output,
            fieldnames=MEASUREMENT_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for item in measurements:
            writer.writerow(
                {
                    "mode": item.mode,
                    "case_id": item.case_id,
                    "case_label": item.case_label,
                    "family": item.family,
                    "variant": item.variant,
                    "size": item.size,
                    "tool": item.tool,
                    "input_bytes": item.input_bytes,
                    "output_bytes": item.output_bytes,
                    "wall_ns": fmt_number(item.wall_ns),
                    "wall_std_ns": fmt_number(item.wall_std_ns),
                    "wall_q1_ns": fmt_number(item.wall_q1_ns),
                    "wall_median_ns": fmt_number(item.wall_median_ns),
                    "wall_q3_ns": fmt_number(item.wall_q3_ns),
                    "rss_bytes": fmt_number(item.rss_bytes),
                    "rss_q1_bytes": fmt_number(item.rss_q1_bytes),
                    "rss_median_bytes": fmt_number(item.rss_median_bytes),
                    "rss_q3_bytes": fmt_number(item.rss_q3_bytes),
                    "samples": item.samples,
                    "failed_samples": item.failed_samples,
                    "command": item.command,
                }
            )
    temporary.replace(path)


def read_measurements(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    if not path.is_file():
        raise BenchmarkError(f"missing measurements table: {path}")
    metadata: dict[str, str] = {}
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and "=" in line:
            key, value = line[2:].split("=", 1)
            metadata[key] = value
        elif line and not line.startswith("#"):
            lines.append(line)
    if not lines:
        raise BenchmarkError(f"measurements table has no rows: {path}")
    reader = csv.DictReader(lines, delimiter="\t")
    if tuple(reader.fieldnames or ()) != MEASUREMENT_COLUMNS:
        raise BenchmarkError(f"unexpected measurements columns: {path}")
    rows = list(reader)
    if len(rows) != 450:
        raise BenchmarkError(f"expected 450 measurement rows, found {len(rows)}")
    if any(int(row["failed_samples"]) != 0 for row in rows):
        raise BenchmarkError("measurements table contains failed samples")
    for mode in MODES:
        mode_rows = [row for row in rows if row["mode"] == mode]
        expected_tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        if len(mode_rows) != 25 * len(expected_tools):
            raise BenchmarkError(f"incomplete measurement mode: {mode}")
        for tool in expected_tools:
            tool_rows = [row for row in mode_rows if row["tool"] == tool]
            if len(tool_rows) != 25 or len({row["case_id"] for row in tool_rows}) != 25:
                raise BenchmarkError(f"incomplete measurement rows: {mode}/{tool}")
    return metadata, rows


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def geometric_mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values or any(value <= 0 for value in values):
        raise BenchmarkError("geometric mean needs positive values")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def row_float(row: dict[str, str], name: str) -> float:
    return float(row[name])


def build_summary(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], dict[str, str]] = {
        (row["mode"], row["case_id"], row["tool"]): row for row in rows
    }
    output: list[dict[str, object]] = []
    for mode in MODES:
        case_ids = sorted({row["case_id"] for row in rows if row["mode"] == mode})
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        for tool in tools:
            values = [grouped[(mode, case_id, tool)] for case_id in case_ids]
            if len(values) != len(case_ids):
                raise BenchmarkError(f"missing {tool} values in {mode}")
            baseline = [grouped[(mode, case_id, "b64z")] for case_id in case_ids]
            time_ratios = [
                row_float(row, "wall_ns") / row_float(base, "wall_ns")
                for row, base in zip(values, baseline, strict=True)
            ]
            rss_ratios = [
                row_float(row, "rss_bytes") / row_float(base, "rss_bytes")
                for row, base in zip(values, baseline, strict=True)
            ]
            huge_row = next(row for row in values if row["case_id"] == "general-huge")
            output.append(
                {
                    "mode": mode,
                    "tool": tool,
                    "cases": len(values),
                    "time_ratio": geometric_mean(time_ratios),
                    "rss_ratio": geometric_mean(rss_ratios),
                    "time_iqr_low": percentile(time_ratios, 0.25),
                    "time_iqr_high": percentile(time_ratios, 0.75),
                    "rss_iqr_low": percentile(rss_ratios, 0.25),
                    "rss_iqr_high": percentile(rss_ratios, 0.75),
                    "faster_than_b64z": "-" if tool == "b64z" else sum(ratio < 1.0 for ratio in time_ratios),
                    "lower_rss_than_b64z": "-" if tool == "b64z" else sum(ratio < 1.0 for ratio in rss_ratios),
                    "huge_time_ms": row_float(huge_row, "wall_ns") / 1_000_000.0,
                    "huge_rss_mib": row_float(huge_row, "rss_bytes") / (1024.0 * 1024.0),
                }
            )
    return output


def write_summary(path: Path, summary: list[dict[str, object]]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=SUMMARY_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in summary:
            writer.writerow(
                {
                    key: fmt_number(value) if isinstance(value, float) else value
                    for key, value in row.items()
                }
            )
    temporary.replace(path)


def title_for_mode(mode: str) -> str:
    return mode.replace("-", " ").title()


def gnuplot_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "\\'") + "'"


def run_gnuplot(script: str) -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".gnuplot", dir=WORK_ROOT, delete=False, encoding="utf-8"
    ) as file:
        file.write(script)
        script_path = Path(file.name)
    try:
        result = subprocess.run(
            ["gnuplot", str(script_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise BenchmarkError(f"gnuplot failed: {result.stderr.strip()}")
    finally:
        script_path.unlink(missing_ok=True)


def normalize_svg(path: Path) -> None:
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def terminal_script(output: Path, body: str) -> str:
    svg = output.with_suffix(".svg")
    png = output.with_suffix(".png")
    return f"""
set encoding utf8
set terminal svg size 1800,1100 dynamic enhanced font "DejaVu Sans,16"
set output {gnuplot_quote(svg)}
{body}
set output
set terminal pngcairo size 1800,1100 enhanced font "DejaVu Sans,16"
set output {gnuplot_quote(png)}
{body}
set output
"""


def write_scaling_data(
    rows: list[dict[str, str]], directory: Path
) -> dict[tuple[str, str], Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    for mode in MODES:
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        for tool in tools:
            path = directory / f"scaling-{mode}-{tool}.dat"
            with path.open("w", encoding="utf-8") as output:
                for index, size in enumerate(SIZE_NAMES, start=1):
                    values = [
                        row
                        for row in rows
                        if row["mode"] == mode
                        and row["tool"] == tool
                        and row["size"] == size
                    ]
                    if len(values) != 5:
                        raise BenchmarkError(
                            f"expected five data cases for {mode}/{tool}/{size}"
                        )
                    throughput = []
                    for row in values:
                        bytes_processed = int(
                            row["input_bytes"]
                            if mode.startswith("encode-")
                            else row["output_bytes"]
                        )
                        throughput.append(
                            bytes_processed
                            / float(row["wall_ns"])
                            * 1_000_000_000
                            / (1024.0**3)
                        )
                    output.write(
                        f"{index}\t{fmt_number(geometric_mean(throughput))}\n"
                    )
            paths[(mode, tool)] = path
    return paths


def scaling_body(data_paths: dict[tuple[str, str], Path]) -> str:
    panels: list[str] = []
    for panel, mode in enumerate(MODES):
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        plots = []
        for tool in tools:
            plots.append(
                f"{gnuplot_quote(data_paths[(mode, tool)])} using 1:2 with linespoints "
                f"lw 3 pt {MARKERS[tool]} ps 1.25 lc rgb {gnuplot_quote(COLORS[tool])} "
                f"title {gnuplot_quote('B64Z' if tool == 'b64z' else PEER_BY_ID[tool].label)}"
            )
        ylabel = "Throughput (GiB/s)" if panel % 2 == 0 else ""
        panels.append(
            "set title "
            + gnuplot_quote(title_for_mode(mode))
            + " font ',17'\n"
            + "set xlabel ''\n"
            + f"set ylabel {gnuplot_quote(ylabel)}\n"
            + "set xrange [0.8:5.2]\n"
            + "set xtics ('tiny' 1, 'small' 2, 'medium' 3, 'large' 4, 'huge' 5) font ',12'\n"
            + "set logscale y\n"
            + "set format y '%.2g'\n"
            + "set grid xtics ytics lc rgb '#E5E7EB' lw 1\n"
            + "set key top left inside opaque box font ',12'\n"
            + "plot "
            + GNUPLOT_PLOT_SEPARATOR.join(plots)
            + "\n"
        )
    return (
        "set label 100 'B64Z Linux x86-64: throughput by input size' at screen 0.5,0.985 center font ',22'\n"
        "set label 101 'geometric mean of general, float32, and float64 cases at each size' at screen 0.5,0.955 center font ',13' textcolor rgb '#4B5563'\n"
        "set multiplot layout 2,2 rowsfirst margins 0.09,0.98,0.09,0.87 spacing 0.10,0.13\n"
        + "\n".join(panels)
        + "\nunset multiplot\n"
    )


def write_isocost_data(
    summary: list[dict[str, object]], directory: Path
) -> dict[tuple[str, str], Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    for mode in MODES:
        for row in [item for item in summary if item["mode"] == mode]:
            path = directory / f"isocost-{mode}-{row['tool']}.dat"
            path.write_text(
                "\t".join(
                    fmt_number(float(row[key]))
                    for key in (
                        "time_ratio",
                        "rss_ratio",
                        "time_iqr_low",
                        "time_iqr_high",
                        "rss_iqr_low",
                        "rss_iqr_high",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            paths[(mode, str(row["tool"]))] = path
    return paths


def isocost_body(
    summary: list[dict[str, object]], data_paths: dict[tuple[str, str], Path]
) -> str:
    panels: list[str] = []
    for panel, mode in enumerate(MODES):
        mode_summary = [row for row in summary if row["mode"] == mode]
        max_time = max(float(row["time_iqr_high"]) for row in mode_summary)
        max_rss = max(float(row["rss_iqr_high"]) for row in mode_summary)
        x_high = max(1.4, max_time * 1.14)
        y_high = max(1.4, max_rss * 1.14)
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        plots = []
        for tool in tools:
            plots.append(
                f"{gnuplot_quote(data_paths[(mode, tool)])} using 1:2:3:4:5:6 with xyerrorbars "
                f"lw 1.5 pt {MARKERS[tool]} ps 1.35 lc rgb {gnuplot_quote(COLORS[tool])} "
                f"title {gnuplot_quote('B64Z' if tool == 'b64z' else PEER_BY_ID[tool].label)}"
            )
        ylabel = "Peak RSS / B64Z" if panel % 2 == 0 else ""
        panels.append(
            "set title "
            + gnuplot_quote(title_for_mode(mode))
            + " font ',17'\n"
            + "set xlabel 'Wall time / B64Z'\n"
            + f"set ylabel {gnuplot_quote(ylabel)}\n"
            + f"set xrange [0.9:{fmt_number(x_high)}]\n"
            + f"set yrange [0.9:{fmt_number(y_high)}]\n"
            + "set xtics 0.5 font ',12'\n"
            + "set ytics 0.5 font ',12'\n"
            + "set grid xtics ytics lc rgb '#E5E7EB' lw 1\n"
            + "set arrow 90 from 1, graph 0 to 1, graph 1 nohead dt 2 lc rgb '#9CA3AF' lw 1\n"
            + "set arrow 91 from graph 0, first 1 to graph 1, first 1 nohead dt 2 lc rgb '#9CA3AF' lw 1\n"
            + "set key top left inside opaque box font ',12'\n"
            + "plot "
            + GNUPLOT_PLOT_SEPARATOR.join(plots)
            + "\n"
        )
    return (
        "set label 100 'B64Z Linux x86-64: speed and memory summary' at screen 0.5,0.985 center font ',22'\n"
        "set label 101 'points are geometric means; bars show the middle 50% of 25 cases' at screen 0.5,0.955 center font ',13' textcolor rgb '#4B5563'\n"
        "set multiplot layout 2,2 rowsfirst margins 0.10,0.98,0.09,0.87 spacing 0.10,0.13\n"
        + "\n".join(panels)
        + "\nunset multiplot\n"
    )


def render_figures(
    target: Target, rows: list[dict[str, str]], summary: list[dict[str, object]]
) -> None:
    output = target.directory / "figures"
    output.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"plots-{target.id}-", dir=WORK_ROOT
    ) as directory:
        plot_data = Path(directory)
        scaling_paths = write_scaling_data(rows, plot_data)
        isocost_paths = write_isocost_data(summary, plot_data)
        run_gnuplot(terminal_script(output / "scaling", scaling_body(scaling_paths)))
        normalize_svg(output / "scaling.svg")
        run_gnuplot(terminal_script(output / "isocost", isocost_body(summary, isocost_paths)))
        normalize_svg(output / "isocost.svg")


def format_ratio(value: float) -> str:
    return f"{value:.3f}x"


def format_ms(value: float) -> str:
    return f"{value:.3f}"


def format_mib(value: float) -> str:
    return f"{value:.2f}"


def result_notes(summary: list[dict[str, object]]) -> list[str]:
    notes = ["## Reading the result", ""]
    for mode in MODES:
        rows = [row for row in summary if row["mode"] == mode]
        peers = [row for row in rows if row["tool"] != "b64z"]
        faster = [
            PEER_BY_ID[str(row["tool"])].label
            for row in peers
            if float(row["time_ratio"]) < 1.0
        ]
        slower = [
            PEER_BY_ID[str(row["tool"])].label
            for row in peers
            if float(row["time_ratio"]) > 1.0
        ]
        lower_rss = [
            PEER_BY_ID[str(row["tool"])].label
            for row in peers
            if float(row["rss_ratio"]) < 1.0
        ]
        if faster:
            time_text = f"lower geometric-mean time than {', '.join(faster)}"
            if slower:
                time_text += f"; higher than {', '.join(slower)}"
        else:
            time_text = "the lowest geometric-mean time among the listed rows"
        rss_text = (
            f"Lower geometric-mean RSS: {', '.join(lower_rss)}."
            if lower_rss
            else "No listed peer has lower geometric-mean RSS."
        )
        notes.append(f"- `{mode}`: B64Z has {time_text}. {rss_text}")
    notes.append("")
    return notes


def report_text(
    target: Target,
    metadata: dict[str, str],
    rows: list[dict[str, str]],
    summary: list[dict[str, object]],
) -> str:
    by_mode = {
        mode: [row for row in summary if row["mode"] == mode] for mode in MODES
    }
    verification = metadata.get("verification", "unknown")
    verification_line = (
        "Correctness checks passed for B64Z and every selected peer. The run checks valid fixtures, invalid B64Z error cases, and all 25 benchmark inputs before timing."
        if verification == "passed"
        else "Correctness checks were skipped for this run. Do not publish this report as a byte-qualified comparison."
    )
    control_time = [
        float(value)
        for key, value in metadata.items()
        if key.startswith("control_") and key.endswith("_time_gap")
    ]
    control_line = (
        f"The largest B64Z A/A mean-time gap on the huge general input was `{max(control_time) * 100:.2f}%` across the four modes."
        if control_time
        else "The report has no B64Z A/A control measurement."
    )
    lines = [
        f"# B64Z benchmark: {target.id}",
        "",
        f"Generated: `{metadata.get('generated_utc', 'unknown')}`",
        "",
        f"B64Z: `{metadata.get('b64z_version', 'unknown')}`",
        "",
        "## Result",
        "",
        "B64Z is the 1.0x reference in each mode. Time and RSS ratios use the geometric mean of 25 input cases. Values above 1.0x mean that the tool took more time or used more RSS than B64Z.",
        "",
        "The memory and streaming rows stay separate. A peer appears only in the mode that its selected executable actually runs.",
        "",
        "| Mode | Tool | Time / B64Z | RSS / B64Z | Faster than B64Z | Lower RSS than B64Z | Huge time (ms) | Huge RSS (MiB) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        for row in by_mode[mode]:
            label = "B64Z" if row["tool"] == "b64z" else PEER_BY_ID[str(row["tool"])].label
            lines.append(
                f"| `{mode}` | {label} | {format_ratio(float(row['time_ratio']))} | {format_ratio(float(row['rss_ratio']))} | {row['faster_than_b64z']} | {row['lower_rss_than_b64z']} | {format_ms(float(row['huge_time_ms']))} | {format_mib(float(row['huge_rss_mib']))} |"
            )
    lines.extend(
        [
            "",
            "`Faster than B64Z` and `Lower RSS than B64Z` count cases where the peer is strictly below the B64Z value. They are not a combined score.",
            "",
            "## Figures",
            "",
            "The throughput figure averages the five data forms at each size: general bytes, float32 raw, float32 zlib, float64 raw, and float64 zlib. The isocost figure summarizes all 25 cases and shows the middle 50% of per-case ratios as bars.",
            "",
            "![Throughput by input size](figures/scaling.svg)",
            "",
            "![Speed and memory ratios](figures/isocost.svg)",
            "",
            "PNG versions are included beside the SVG figures.",
            "",
            "## What was measured",
            "",
            "Each row starts one named command for one input. The command reads a file and writes Base64 or decoded bytes to standard output. Zebrac discards child output during timing, so byte comparison runs before measurement. Process startup, file reads, allocation, encoding or decoding, and standard-output writes are included in the measured process.",
            "",
            f"Zebrac ran `{metadata.get('samples', 'unknown')}` measured samples after `{metadata.get('warmup', 'unknown')}` warmups, with a `{metadata.get('duration_ms', 'unknown')} ms` duration ceiling and an exact maximum sample count. Every recorded command has zero failed samples.",
            "",
            f"B64Z uses chunk `{CHUNKS['encode-memory']}` for both memory command lines and chunks `{CHUNKS['encode-streaming']}` and `{CHUNKS['decode-streaming']}` for the two streaming command lines. The memory command passes the chunk flag for a stable command record; its whole-file path does not use the streaming buffer.",
            "",
            verification_line,
            "",
            "The byte checks compare B64Z and every selected peer against the canonical padded bytes produced by Aklomp.",
            "",
            control_line,
            "",
            "## Data",
            "",
            "The benchmark contains 25 byte inputs: 5 general inputs, 10 float32 mzML payload inputs, and 10 float64 mzML payload inputs. Each family has tiny, small, medium, large, and huge sizes at 256 B, 16 KiB, 1 MiB, 8 MiB, and 32 MiB. The zlib files are compressed payload bytes, not XML documents.",
            "",
            "## Tools and versions",
            "",
            "| Tool | Selected modes | Version or build |",
            "| --- | --- | --- |",
            f"| B64Z | all four | `{metadata.get('b64z_version', 'unknown')}`; `zig -Dcpu={target.cpu} -Doptimize=ReleaseFast -Dstrip=true` |",
        ]
    )
    for peer in PEERS:
        lines.append(
            f"| {peer.label} | {', '.join(peer.modes)} | `{peer.version}` |"
        )
    lines.extend(
        [
            "",
            "Aklomp and GNU Coreutils appear only in streaming rows because their selected commands process files incrementally. simdutf, Turbo-Base64, Rust base64, Rust base64-simd, and Zig std.base64 appear only in memory rows because their selected adapters allocate complete input and output buffers.",
            "",
        ]
    )
    lines.extend(result_notes(summary))
    lines.extend(
        [
            "## Run conditions",
            "",
            f"- Host: `{metadata.get('cpu_model', 'unknown')}`, `{metadata.get('architecture', 'unknown')}`, `{metadata.get('cpu_count', 'unknown')} logical CPUs`.",
            f"- Kernel: `{metadata.get('kernel', 'unknown')}`; CPU governor: `{metadata.get('cpu_governor', 'unknown')}`.",
            f"- Git commit: `{metadata.get('git_commit', 'unknown')}`; worktree changes at measurement time: `{metadata.get('git_changes', 'unknown')}`.",
            f"- Runner: `{metadata.get('zebrac_version', 'unknown')}`; gnuplot: `{metadata.get('gnuplot_version', 'unknown')}`; Zig: `{metadata.get('zig_version', 'unknown')}`.",
            f"- Host tools: GCC `{metadata.get('gcc_version', 'unknown')}`; Clang `{metadata.get('clang_version', 'unknown')}`; Rust `{metadata.get('rustc_version', 'unknown')}`; Cargo `{metadata.get('cargo_version', 'unknown')}`; CMake `{metadata.get('cmake_version', 'unknown')}`; Make `{metadata.get('make_version', 'unknown')}`.",
            "- The file cache is warm after verification. The runner does not pin processes to a CPU or flush the page cache.",
            "- These numbers describe the named commands, adapters, and builds on this host. They do not describe a peer library without its command adapter or a different compiler build.",
            "- The target choice changes the B64Z build only. Peer binaries keep their own native build and runtime dispatch settings. The scalar page is not a scalar-for-every-peer instruction-set test.",
            "",
            "## Files",
            "",
            "- [`measurements.tsv`](measurements.tsv) contains one row for every measured command and input, including sample quartiles and a public command label.",
            "- [`summary.tsv`](summary.tsv) contains the values used by the tables and figures.",
            "",
            "The report does not produce one report per input. The table and the two figures cover the complete 100 groups without turning each input into a separate publication page.",
            "",
        ]
    )
    return "\n".join(lines)


def render(target: Target) -> None:
    target_dir = target.directory
    metadata, rows = read_measurements(target_dir / "measurements.tsv")
    summary = build_summary(rows)
    write_summary(target_dir / "summary.tsv", summary)
    render_figures(target, rows, summary)
    report = report_text(target, metadata, rows, summary)
    temporary = target_dir / f".README.md.{os.getpid()}.tmp"
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(target_dir / "README.md")


def run(arguments: argparse.Namespace) -> None:
    target = TARGETS[arguments.target]
    cases = discover_cases()
    require_files(target)
    generated = prepare_inputs(cases)
    zebrac = zebrac_path()
    metadata = environment_metadata(
        target,
        zebrac,
        now_utc(),
        f"{generated} regenerated",
        "skipped" if arguments.skip_verify else "passed",
    )
    metadata.update(
        {
            "runs": str(arguments.runs),
            "samples": str(arguments.runs),
            "warmup": str(arguments.warmup),
            "duration_ms": str(arguments.duration),
            "case_count": str(len(cases)),
            "group_count": str(len(MODES) * len(cases)),
        }
    )
    if not arguments.skip_verify:
        print("verifying canonical bytes before timing")
        print(verify(target, cases))
        metadata["verification"] = "passed"
    else:
        print("verification skipped by request")
    if not arguments.skip_benchmarks:
        print(
            f"measuring {target.id} with {arguments.runs} samples and {arguments.warmup} warmups"
        )
        measurements, controls = measure(
            target, cases, arguments.runs, arguments.warmup, arguments.duration, zebrac
        )
        write_measurements(
            target.directory / "measurements.tsv", measurements, metadata, controls
        )
    if not arguments.skip_report:
        render(target)
        print(f"report: {target.directory / 'README.md'}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="bench/report.py")
    commands = result.add_subparsers(dest="action", required=True)
    run_parser = commands.add_parser("run", help="verify, measure, and render one target")
    run_parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    run_parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    run_parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    run_parser.add_argument("--duration", type=int, default=DEFAULT_DURATION_MS)
    run_parser.add_argument("--skip-verify", action="store_true")
    run_parser.add_argument("--skip-benchmarks", action="store_true")
    run_parser.add_argument("--skip-report", action="store_true")
    run_parser.set_defaults(handler=run)

    render_parser = commands.add_parser(
        "render", help="render a report from measurements.tsv"
    )
    render_parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    render_parser.set_defaults(handler=lambda args: render(TARGETS[args.target]))
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.action == "run":
            if arguments.runs < 1 or arguments.warmup < 0 or arguments.duration < 1:
                raise BenchmarkError(
                    "runs must be >= 1, warmup must be >= 0, and duration must be >= 1"
                )
        arguments.handler(arguments)
    except (BenchmarkError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
