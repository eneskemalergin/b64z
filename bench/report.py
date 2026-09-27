#!/usr/bin/env python3
"""Build, verify, measure, and render the two retained B64Z benchmark reports."""

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
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.peer_config import PEERS, PEER_BY_ID, Peer, aklomp_command, peer_command

BENCH_ROOT = ROOT / "bench"
DATA_ROOT = ROOT / "data"
BENCH_DATA_ROOT = DATA_ROOT / "bench"
FIXTURE_ROOT = DATA_ROOT / "fixture"
WORK_ROOT = BENCH_ROOT / "work"
REFERENCE_BINARY = PEER_BY_ID["aklomp"].executable
REFERENCE_CACHE = WORK_ROOT / "inputs" / "reference.cache"

MODES = (
    "encode-memory",
    "encode-streaming",
    "decode-memory",
    "decode-streaming",
)
SIZE_NAMES = ("tiny", "small", "medium", "large", "huge")
SIZE_BYTES = (256, 16 * 1024, 1024**2, 8 * 1024**2, 32 * 1024**2)
CHUNKS = {
    "encode-streaming": 8191,
    "decode-streaming": 4093,
}
FIXTURE_CHUNKS = {
    "encode-memory": None,
    "encode-streaming": 7,
    "decode-memory": None,
    "decode-streaming": 5,
}
DEFAULT_RUNS = 20
DEFAULT_WARMUP = 5
DEFAULT_DURATION_MS = 15000

PLOT_THEMES = {
    "light": {
        "background": "#FFFFFF",
        "foreground": "#202B38",
        "muted": "#526171",
        "grid": "#E5EAF0",
        "reference": "#8693A1",
        "curve": "#B5BFC9",
        "colors": {
            "b64z": "#996515",
            "aklomp": "#0072B2",
            "coreutils": "#52606D",
            "simdutf": "#007B65",
            "turbo": "#C34B24",
            "rust-base64": "#A64C79",
            "rust-simd": "#007C91",
            "zig-std": "#7551A4",
        },
    },
    "dark": {
        "background": "#101820",
        "foreground": "#E8EDF2",
        "muted": "#ADBCCA",
        "grid": "#283540",
        "reference": "#778A9B",
        "curve": "#4C606F",
        "colors": {
            "b64z": "#F2C05A",
            "aklomp": "#56B4E9",
            "coreutils": "#B7C4D2",
            "simdutf": "#5DC6A5",
            "turbo": "#F38B72",
            "rust-base64": "#E6A0C4",
            "rust-simd": "#60C8DE",
            "zig-std": "#BCA3EA",
        },
    },
}
MARKERS = {
    "b64z": 7,
    "aklomp": 5,
    "coreutils": 13,
    "simdutf": 9,
    "turbo": 11,
    "rust-base64": 4,
    "rust-simd": 12,
    "zig-std": 6,
}
DASHES = {
    "b64z": 1,
    "aklomp": 2,
    "coreutils": 3,
    "simdutf": 4,
    "turbo": 5,
    "rust-base64": 6,
    "rust-simd": 7,
    "zig-std": 8,
}
COST_LEVELS = (1.0, 2.0, 4.0, 8.0, 16.0)
GNUPLOT_PLOT_SEPARATOR = ", " + chr(92) + "\n    "
RATIO_TICS = "('0.25' 0.25, '0.5' 0.5, '1' 1, '2' 2, '4' 4, '8' 8, '16' 16, '32' 32)"


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


def build_target(arguments: argparse.Namespace) -> None:
    target = TARGETS[arguments.target]
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise BenchmarkError("the benchmark runner requires Linux x86_64")
    if target.backend == "avx2":
        try:
            cpu_info = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        except OSError as error:
            raise BenchmarkError(f"cannot inspect /proc/cpuinfo: {error}") from error
        has_avx2 = any(
            "avx2" in line.split()
            for line in cpu_info.splitlines()
            if line.startswith("flags")
        )
        if not has_avx2:
            raise BenchmarkError("this CPU does not report AVX2")

    zig = shutil.which("zig")
    if zig is None:
        raise BenchmarkError("zig is not on PATH")
    command = [
        zig,
        "build",
        f"-Dcpu={target.cpu}",
        "-Doptimize=ReleaseFast",
        "-Dstrip=true",
        "--prefix",
        str(target.directory),
    ]
    print(f"building {target.id} with zig build -Dcpu={target.cpu} -Doptimize=ReleaseFast -Dstrip=true")
    result = run_command(command)
    if result.returncode != 0:
        raise BenchmarkError(
            "B64Z build failed: " + error_text(result)
        )
    version = version_text([str(target.binary), "--version"])
    if f"backend={target.backend}" not in version or "optimize=ReleaseFast" not in version:
        raise BenchmarkError(f"unexpected B64Z build: {version}")
    print(version)


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
        command = aklomp_command(case.raw_path)
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
    command = [str(target.binary), "--mode", mode]
    selected_chunk = CHUNKS.get(mode) if chunk is None else chunk
    if selected_chunk is not None:
        command.extend(("--chunk", str(selected_chunk)))
    command.append(str(input_path))
    return command


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
        command = ["B64Z", "--mode", mode]
        if mode in CHUNKS:
            command.extend(("--chunk", str(CHUNKS[mode])))
        command.append("INPUT")
        return shlex.join(command)
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
            for mode in ("encode-memory", "encode-streaming"):
                compare_output(
                    b64z_command(target, mode, raw_path, FIXTURE_CHUNKS[mode]),
                    encoded_path,
                    temporary / f"target-{raw_path.stem}-{mode}.b64",
                    f"B64Z {mode} fixture {raw_path.name}",
                )
                target_checks += 1
            for mode in ("decode-memory", "decode-streaming"):
                compare_output(
                    b64z_command(target, mode, encoded_path, FIXTURE_CHUNKS[mode]),
                    raw_path,
                    temporary / f"target-{raw_path.stem}-{mode}.bin",
                    f"B64Z {mode} fixture {raw_path.name}",
                )
                target_checks += 1
            compare_output(
                aklomp_command(raw_path),
                encoded_path,
                temporary / f"reference-{raw_path.stem}.b64",
                f"Aklomp encode fixture {raw_path.name}",
            )
            compare_output(
                aklomp_command(encoded_path, decode=True),
                raw_path,
                temporary / f"reference-{raw_path.stem}.bin",
                f"Aklomp decode fixture {raw_path.name}",
            )
            reference_checks += 2

        for encoded_path in invalid:
            expected_error = encoded_path.with_suffix(".error").read_text(encoding="utf-8").strip()
            for mode in ("decode-memory", "decode-streaming"):
                output = temporary / f"target-invalid-{encoded_path.stem}-{mode}.bin"
                result = write_process_output(
                    b64z_command(target, mode, encoded_path, FIXTURE_CHUNKS[mode]), output
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
    generated_reports = [
        f":(exclude)bench/{target.id}/{name}"
        for target in TARGETS.values()
        for name in ("README.md", "measurements.tsv", "summary.tsv")
    ]
    generated_reports.extend(
        f":(exclude,glob)bench/{target.id}/figures/*.svg"
        for target in TARGETS.values()
    )
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            *generated_reports,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def require_clean_worktree(action: str) -> None:
    if git_has_changes():
        raise BenchmarkError(
            f"refusing to {action} with project changes in the Git worktree; "
            "commit or clean those changes first"
        )


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
    operation, storage = mode.split("-")
    return f"{operation.title()} / {storage}"


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
    title = f"B64Z {path.parents[1].name.removeprefix('linux-x86-').upper()}: {path.stem.replace('-', ' ')}"
    svg = path.read_text(encoding="utf-8").replace("<title>Gnuplot</title>", f"<title>{title}</title>")
    svg = svg.replace('font-family="DejaVu Sans"', 'font-family="DejaVu Sans,Arial,sans-serif"')
    lines = [line.rstrip() for line in svg.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def terminal_script(
    output: Path,
    body: str,
    theme_name: str,
    size: tuple[int, int] = (1280, 1000),
) -> str:
    svg = output.with_suffix(".svg")
    theme = PLOT_THEMES[theme_name]
    return f"""
set encoding utf8
set terminal svg size {size[0]},{size[1]} dynamic enhanced font "DejaVu Sans,18" rounded background rgb {gnuplot_quote(theme['background'])}
set output {gnuplot_quote(svg)}
set border 3 lw 1 lc rgb {gnuplot_quote(theme['reference'])}
set tics out nomirror scale 0.4 font ',16' textcolor rgb {gnuplot_quote(theme['muted'])}
unset mxtics
unset mytics
set grid back xtics ytics lc rgb {gnuplot_quote(theme['grid'])} lw 1 dt 1
set bars 0.5
set key noopaque nobox reverse Left samplen 1.8 spacing 1.4 font ',16' textcolor rgb {gnuplot_quote(theme['foreground'])}
set style textbox opaque noborder fillcolor rgb {gnuplot_quote(theme['background'])} margins 0.3,0.2
set title textcolor rgb {gnuplot_quote(theme['foreground'])}
set xlabel textcolor rgb {gnuplot_quote(theme['foreground'])}
set ylabel textcolor rgb {gnuplot_quote(theme['foreground'])}
{body}
set output
"""


def series_style(tool: str, theme_name: str, dashed: bool = False) -> str:
    color = PLOT_THEMES[theme_name]["colors"][tool]
    return f"lc rgb '{color}' lw 2.2 dt {DASHES[tool] if dashed else 1} pt {MARKERS[tool]} ps 1.0"


def figure_header(title: str, subtitle: str, footer: str, theme_name: str) -> str:
    theme = PLOT_THEMES[theme_name]
    return f"""
set label 100 {gnuplot_quote(title)} at screen 0.075,0.965 left font 'DejaVu Sans,26' tc rgb '{theme['foreground']}'
set label 101 {gnuplot_quote(subtitle)} at screen 0.075,0.924 left font ',16' tc rgb '{theme['muted']}'
set label 102 {gnuplot_quote(footer)} at screen 0.075,0.026 left font ',14' tc rgb '{theme['muted']}'
"""


def panel_plot(panel: int, mode: str, plots: list[str], theme_name: str, style: str) -> str:
    theme = PLOT_THEMES[theme_name]
    if panel == 0:
        for tool in ("b64z", *(peer.id for peer in PEERS)):
            label = "B64Z" if tool == "b64z" else PEER_BY_ID[tool].label
            plots.append(f"keyentry with {style} {series_style(tool, theme_name, style == 'linespoints')} title {gnuplot_quote(label)}")
    return f"""
set label 300 {gnuplot_quote(f'({chr(97 + panel)})  {title_for_mode(mode)}')} at graph 0,1.08 left font ',18' tc rgb '{theme['foreground']}'
{'set key at screen 0.52,0.858 center horizontal columns 4 keywidth screen 0.86' if panel == 0 else 'unset key'}
plot {GNUPLOT_PLOT_SEPARATOR.join(plots)}
unset label 100
unset label 101
unset label 102
"""


def ratio_range(values: Iterable[float]) -> tuple[float, float]:
    values = [1.0, *values]
    return min(values) / 1.2, max(values) * 1.2


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
                for size, nominal_bytes in zip(SIZE_NAMES, SIZE_BYTES, strict=True):
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
                        f"{nominal_bytes}\t{fmt_number(geometric_mean(throughput))}\n"
                    )
            paths[(mode, tool)] = path
    return paths


def summary_positions() -> dict[tuple[str, str], float]:
    positions = {}
    y = 0.0
    for mode in MODES:
        for peer in PEERS:
            if mode in peer.modes:
                positions[(mode, peer.id)] = y
                y -= 1
        y -= 1.4
    return positions


def write_summary_data(
    summary: list[dict[str, object]], directory: Path
) -> dict[tuple[str, str], Path]:
    directory.mkdir(parents=True, exist_ok=True)
    positions = summary_positions()
    paths = {}
    for metric in ("time", "rss"):
        for peer in PEERS:
            path = directory / f"summary-{metric}-{peer.id}.dat"
            lines = []
            for row in summary:
                if row["tool"] == peer.id:
                    values = (
                        float(row[f"{metric}_ratio"]),
                        positions[(str(row["mode"]), peer.id)],
                        float(row[f"{metric}_iqr_low"]),
                        float(row[f"{metric}_iqr_high"]),
                    )
                    lines.append("\t".join(fmt_number(value) for value in values))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            paths[(metric, peer.id)] = path
    return paths


def summary_body(
    target: Target,
    summary: list[dict[str, object]],
    data_paths: dict[tuple[str, str], Path],
    theme_name: str,
) -> str:
    theme = PLOT_THEMES[theme_name]
    positions = summary_positions()
    x_low, x_high = ratio_range(
        float(row[f"{metric}_{field}"])
        for row in summary
        for metric in ("time", "rss")
        for field in ("ratio", "iqr_low", "iqr_high")
    )
    ytics = ", ".join(
        f"{gnuplot_quote(PEER_BY_ID[tool].label)} {y:g}"
        for (_, tool), y in positions.items()
    )
    panels = []
    for panel, (metric, title) in enumerate(
        (("time", "Wall time / B64Z"), ("rss", "Peak RSS / B64Z"))
    ):
        labels, plots = [], []
        if panel == 0:
            for index, mode in enumerate(MODES):
                y = max(y for (row_mode, _), y in positions.items() if row_mode == mode)
                labels.append(
                    f"set label {200 + index} {gnuplot_quote(title_for_mode(mode))} "
                    f"at screen 0.035, first {y + 0.85:g} left font ',16' tc rgb '{theme['foreground']}'"
                )
        for peer in PEERS:
            data = gnuplot_quote(data_paths[(metric, peer.id)])
            plots.append(
                f"{data} using 1:2:3:4 with xerrorbars {series_style(peer.id, theme_name)} notitle"
            )
        for index, row in enumerate(summary):
            if row["tool"] != "b64z":
                y = positions[(str(row["mode"]), str(row["tool"]))]
                labels.append(
                    f"set label {400 + index} '{float(row[f'{metric}_ratio']):.2f}x' "
                    f"at graph 1.03, first {y:g} left font ',15' tc rgb '{theme['foreground']}'"
                )
        panels.append(f"""
set label 300 {gnuplot_quote(title)} at graph 0,1.085 left font ',19' tc rgb '{theme['foreground']}'
set label 301 'B64Z = 1' at first 1, graph 1.02 left font ',13' tc rgb '{theme['colors']['b64z']}'
set label 302 'Mean' at graph 1.03,1.02 left font ',13' tc rgb '{theme['muted']}'
{chr(10).join(labels)}
unset key
set border 1
set logscale x
set xrange [{x_low:g}:{x_high:g}]
set yrange [{min(positions.values()) - 0.8:g}:1.5]
set xtics {RATIO_TICS}
set ytics ({ytics}) scale 0 font ',15'
{'unset ytics' if panel else ''}
set grid xtics noytics
set xlabel 'Ratio to B64Z (log scale)' offset 0,-0.3
set arrow 90 from 1, graph 0 to 1, graph 1 nohead lc rgb '{theme['colors']['b64z']}' lw 2 back
plot {GNUPLOT_PLOT_SEPARATOR.join(plots)}
unset label
""")
    return (
        figure_header(
            f"Command time and peak memory | B64Z {target.backend.upper()}",
            "Linux x86-64 | Native peer builds | 25 input cases per mode | Lower ratios are better",
            "Markers: geometric means. Whiskers: middle 50% of cases, not confidence intervals.",
            theme_name,
        )
        + "set multiplot layout 1,2 rowsfirst margins 0.245,0.905,0.17,0.81 spacing 0.13,0\n"
        + "\n".join(panels)
        + "\nunset multiplot\n"
    )


def scaling_body(
    data_paths: dict[tuple[str, str], Path], theme_name: str, target: Target
) -> str:
    values = [
        float(line.split()[1])
        for path in data_paths.values()
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    y_low = 10 ** math.floor(math.log10(min(values)) - 0.05)
    y_high = 10 ** math.ceil(math.log10(max(values)) + 0.05)
    panels = []
    for panel, mode in enumerate(MODES):
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        plots = [
            f"{gnuplot_quote(data_paths[(mode, tool)])} using 1:2 "
            f"with linespoints {series_style(tool, theme_name, dashed=True)} notitle"
            for tool in tools
        ]
        panels.append(f"""
set logscale x 2
set logscale y 10
set xrange [128:67108864]
set yrange [{y_low:g}:{y_high:g}]
set xtics ('256 B' 256, '16 KiB' 16384, '1 MiB' 1048576, '8 MiB' 8388608, '32 MiB' 33554432) font ',14'
set format y '10^{{%L}}'
set xlabel {gnuplot_quote('Nominal input size (log scale)' if panel >= 2 else '')}
set ylabel {gnuplot_quote('Throughput (GiB/s)' if panel % 2 == 0 else '')}
{panel_plot(panel, mode, plots, theme_name, 'linespoints')}
""")
    return (
        figure_header(
            f"Throughput by input size | B64Z {target.backend.upper()}",
            "Linux x86-64 | Native peer builds | Geometric mean of five input forms per size | Higher is better",
            "Sizes refer to the data before compression; throughput uses actual binary bytes. Both axes are logarithmic.",
            theme_name,
        )
        + "set multiplot layout 2,2 rowsfirst margins 0.085,0.975,0.135,0.79 spacing 0.10,0.14\n"
        + "\n".join(panels)
        + "\nunset multiplot\n"
    )


def write_isocost_data(
    rows: list[dict[str, str]],
    summary: list[dict[str, object]],
    directory: Path,
) -> tuple[dict[tuple[str, str], Path], dict[tuple[str, str], Path]]:
    directory.mkdir(parents=True, exist_ok=True)
    summary_paths: dict[tuple[str, str], Path] = {}
    point_paths: dict[tuple[str, str], Path] = {}
    grouped = {
        (row["mode"], row["case_id"], row["tool"]): row for row in rows
    }
    for mode in MODES:
        case_ids = sorted({row["case_id"] for row in rows if row["mode"] == mode})
        for row in [item for item in summary if item["mode"] == mode]:
            tool = str(row["tool"])
            summary_path = directory / f"isocost-{mode}-{tool}.dat"
            summary_path.write_text(
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
            point_path = directory / f"isocost-points-{mode}-{tool}.dat"
            with point_path.open("w", encoding="utf-8") as output:
                for case_id in case_ids:
                    value = grouped[(mode, case_id, tool)]
                    baseline = grouped[(mode, case_id, "b64z")]
                    time_ratio = row_float(value, "wall_ns") / row_float(
                        baseline, "wall_ns"
                    )
                    rss_ratio = row_float(value, "rss_bytes") / row_float(
                        baseline, "rss_bytes"
                    )
                    output.write(
                        f"{fmt_number(time_ratio)}\t{fmt_number(rss_ratio)}\n"
                    )
            summary_paths[(mode, tool)] = summary_path
            point_paths[(mode, tool)] = point_path
    return summary_paths, point_paths


def isocost_body(
    rows: list[dict[str, str]],
    summary: list[dict[str, object]],
    summary_paths: dict[tuple[str, str], Path],
    point_paths: dict[tuple[str, str], Path],
    theme_name: str,
    target: Target | None = None,
) -> str:
    theme = PLOT_THEMES[theme_name]
    colors = theme["colors"]
    baseline = {(row["mode"], row["case_id"]): row for row in rows if row["tool"] == "b64z"}
    limits = {}
    for metric, field in (("time", "wall_ns"), ("rss", "rss_bytes")):
        values = [
            row_float(row, field) / row_float(baseline[(row["mode"], row["case_id"])], field)
            for row in rows
        ]
        values.extend(
            float(row[f"{metric}_{stat}"])
            for row in summary
            for stat in ("ratio", "iqr_low", "iqr_high")
        )
        limits[metric] = ratio_range(values)
    x_low, x_high = limits["time"]
    y_low, y_high = limits["rss"]
    curve_labels = []
    for index, cost in enumerate(COST_LEVELS):
        x = max(x_low * 1.07, cost / (y_high / 1.13))
        y = cost / x
        if x < x_high / 1.1 and y > y_low * 1.1:
            curve_labels.append(
                f"set label {200 + index} 'C = {cost:g}' at first {x:g},{y:g} "
                f"left offset char 0.25,0.35 font ',12' tc rgb '{theme['muted']}' front boxed"
            )
    panels = []
    for panel, mode in enumerate(MODES):
        tools = ["b64z", *(peer.id for peer in PEERS if mode in peer.modes)]
        plots = [
            f"{cost:g}/x with lines lw 1.1 dt 3 lc rgb '{theme['curve']}' notitle"
            for cost in COST_LEVELS
        ]
        # Draw all cases first so they cannot cover the means and quartile intervals.
        for tool in tools:
            if tool != "b64z":
                plots.append(
                    f"{gnuplot_quote(point_paths[(mode, tool)])} using 1:2 with points "
                    f"pt {MARKERS[tool]} ps 0.55 lc rgb '#55{colors[tool][1:]}' notitle"
                )
        for tool in tools:
            plots.append(
                f"{gnuplot_quote(summary_paths[(mode, tool)])} using 1:2:3:4:5:6 "
                f"with xyerrorbars {series_style(tool, theme_name)} notitle"
            )
        panels.append(f"""
set logscale xy 2
set xrange [{x_low:g}:{x_high:g}]
set yrange [{y_low:g}:{y_high:g}]
set xtics {RATIO_TICS}
set ytics {RATIO_TICS}
set xlabel {gnuplot_quote('Wall time / B64Z' if panel >= 2 else '')}
set ylabel {gnuplot_quote('Peak RSS / B64Z' if panel % 2 == 0 else '')}
set arrow 90 from 1, graph 0 to 1, graph 1 nohead dt 2 lc rgb '{theme['reference']}' lw 1.2 back
set arrow 91 from graph 0, first 1 to graph 1, first 1 nohead dt 2 lc rgb '{theme['reference']}' lw 1.2 back
set samples 160
{chr(10).join(curve_labels)}
{panel_plot(panel, mode, plots, theme_name, 'points')}
""")
    backend = f" {target.backend.upper()}" if target else ""
    return (
        figure_header(
            f"Time and memory tradeoffs | B64Z{backend}",
            "Linux x86-64 | Native peer builds | B64Z = 1 | Lower left is better | Both axes are logarithmic",
            "Small marks: cases. Large marks: geometric means. Bars: middle 50% of cases. C = time ratio * RSS ratio.",
            theme_name,
        )
        + "set multiplot layout 2,2 rowsfirst margins 0.085,0.975,0.135,0.79 spacing 0.10,0.14\n"
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
        isocost_summary_paths, isocost_point_paths = write_isocost_data(
            rows, summary, plot_data
        )
        summary_paths = (
            write_summary_data(summary, plot_data)
            if target.id == "linux-x86-avx2"
            else None
        )
        for figure_name in ("scaling", "isocost"):
            for suffix in (".png", ".svg"):
                (output / f"{figure_name}{suffix}").unlink(missing_ok=True)
        for theme_name in PLOT_THEMES:
            figures = {
                "scaling": scaling_body(scaling_paths, theme_name, target),
                "isocost": isocost_body(
                    rows, summary, isocost_summary_paths, isocost_point_paths, theme_name, target
                ),
            }
            if summary_paths is not None:
                figures["summary"] = summary_body(target, summary, summary_paths, theme_name)
            for name, body in figures.items():
                destination = output / f"{name}-{theme_name}"
                size = (1280, 900 if name == "summary" else 1000)
                run_gnuplot(terminal_script(destination, body, theme_name, size))
                normalize_svg(destination.with_suffix(".svg"))


def format_ratio(value: float) -> str:
    return f"{value:.3f}x"


def format_ms(value: float) -> str:
    return f"{value:.3f}"


def format_mib(value: float) -> str:
    return f"{value:.2f}"


def markdown_table(
    headers: list[str], rows: list[list[str]], right_align: tuple[bool, ...]
) -> list[str]:
    if len(headers) != len(right_align):
        raise ValueError("table headers and alignment do not have the same width")
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("table row and header do not have the same width")
    values = [headers, *rows]
    widths = [
        max(len(row[index]) for row in values) for index in range(len(headers))
    ]

    def row_text(row: list[str]) -> str:
        cells = []
        for index, value in enumerate(row):
            width = widths[index]
            cells.append(
                value.rjust(width)
                if right_align[index]
                else value.ljust(width)
            )
        return "| " + " | ".join(cells) + " |"

    separators = []
    for index, width in enumerate(widths):
        separator = "-" * width
        if right_align[index]:
            separator = separator[:-1] + ":"
        separators.append(separator)
    return [row_text(headers), row_text(separators), *(row_text(row) for row in rows)]


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
            time_text = f"higher geometric-mean time than {', '.join(faster)}"
            if slower:
                time_text += f"; lower than {', '.join(slower)}"
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
    result_headers = [
        "Mode",
        "Tool",
        "Time / B64Z",
        "RSS / B64Z",
        "Faster than B64Z",
        "Lower RSS than B64Z",
        "Huge time (ms)",
        "Huge RSS (MiB)",
    ]
    result_rows: list[list[str]] = []
    for mode in MODES:
        for row in by_mode[mode]:
            label = "B64Z" if row["tool"] == "b64z" else PEER_BY_ID[str(row["tool"])].label
            result_rows.append(
                [
                    f"`{mode}`",
                    label,
                    format_ratio(float(row["time_ratio"])),
                    format_ratio(float(row["rss_ratio"])),
                    str(row["faster_than_b64z"]),
                    str(row["lower_rss_than_b64z"]),
                    format_ms(float(row["huge_time_ms"])),
                    format_mib(float(row["huge_rss_mib"])),
                ]
            )
    lines = [
        f"# B64Z benchmark: {target.id}",
        "",
        f"Generated: `{metadata.get('generated_utc', 'unknown')}`",
        "",
        f"B64Z: `{metadata.get('b64z_version', 'unknown')}`",
        "",
        "## Terms",
        "",
        "For B64Z, `memory` means the command reads the complete input into one buffer and converts it in place. `Streaming` means the command uses fixed input and output buffers. The benchmark method and input details are in the [benchmark README](../README.md).",
        "",
        "`Peak RSS` is the per-sample maximum resident set size reported by Zebrac for the timed process. The table and ratios use the mean of those per-sample peaks. It includes the executable, runtime, file I/O buffers, codec state, and resident input or output allocations; it is not the size of one buffer. `RSS / B64Z` compares that process value with B64Z in the same mode and input case.",
        "",
        "The size names refer to the raw case bytes: `tiny` = 256 B, `small` = 16 KiB, `medium` = 1 MiB, `large` = 8 MiB, and `huge` = 32 MiB. Decode modes read the corresponding padded Base64 file, which is larger than the raw case.",
        "",
        "## Result",
        "",
        "B64Z is the 1.0x reference in each mode. Time and RSS ratios use the geometric mean of 25 input cases. Values above 1.0x mean that the tool took more time or used more RSS than B64Z.",
        "",
        "The full-input memory and streaming rows stay separate. A peer appears only in the mode that its selected executable actually runs.",
        "",
    ]
    lines.extend(
        markdown_table(
            result_headers,
            result_rows,
            (False, False, True, True, True, True, True, True),
        )
    )
    lines.extend(
        [
            "",
            "`Faster than B64Z` and `Lower RSS than B64Z` count cases where the peer is strictly below the B64Z value. They are not a combined score.",
            "",
            "## Figures",
            "",
            "The figures use the inputs and method described in the [benchmark README](../README.md).",
            "",
            "<p align=\"center\">",
            "  <picture>",
            "    <source media=\"(prefers-color-scheme: dark)\" srcset=\"figures/scaling-dark.svg\">",
            "    <source media=\"(prefers-color-scheme: light)\" srcset=\"figures/scaling-light.svg\">",
            "    <img src=\"figures/scaling-light.svg\" alt=\"Throughput by input size\" width=\"100%\">",
            "  </picture>",
            "</p>",
            "",
            "<p align=\"center\">",
            "  <picture>",
            "    <source media=\"(prefers-color-scheme: dark)\" srcset=\"figures/isocost-dark.svg\">",
            "    <source media=\"(prefers-color-scheme: light)\" srcset=\"figures/isocost-light.svg\">",
            "    <img src=\"figures/isocost-light.svg\" alt=\"Speed and peak RSS ratios with combined-cost curves\" width=\"100%\">",
            "  </picture>",
            "</p>",
            "",
            "## Measurement",
            "",
            f"Zebrac ran `{metadata.get('samples', 'unknown')}` measured samples after `{metadata.get('warmup', 'unknown')}` warmups, with a `{metadata.get('duration_ms', 'unknown')} ms` duration ceiling and an exact maximum sample count. Every recorded command has zero failed samples.",
            "",
            f"B64Z passes chunks `{CHUNKS['encode-streaming']}` and `{CHUNKS['decode-streaming']}` to the streaming command lines. Memory command lines do not pass `--chunk`.",
            "",
            verification_line,
            "",
            "The byte checks compare B64Z and every selected peer against Aklomp's canonical padded bytes.",
            "",
            control_line,
            "",
            "## Data",
            "",
            "The case sizes, byte forms, and compression details are listed in the [benchmark README](../README.md).",
            "",
            "## Tools and versions",
            "",
            f"- **B64Z** (all four modes): `{metadata.get('b64z_version', 'unknown')}`; `zig -Dcpu={target.cpu} -Doptimize=ReleaseFast -Dstrip=true`.",
        ]
    )
    for peer in PEERS:
        lines.append(
            f"- **{peer.label}** ({', '.join(peer.modes)}): `{peer.version}`."
        )
    lines.extend(
        [
            "",
            "Peer commands and their mode coverage are described in [Local Peer Tools](../../tools/tool.md).",
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
            f"- Git commit: `{metadata.get('git_commit', 'unknown')}`; project changes at measurement time: `{metadata.get('git_changes', 'unknown')}`.",
            f"- Runner: `{metadata.get('zebrac_version', 'unknown')}`; gnuplot: `{metadata.get('gnuplot_version', 'unknown')}`; Zig: `{metadata.get('zig_version', 'unknown')}`.",
            f"- Host tools: GCC `{metadata.get('gcc_version', 'unknown')}`; Clang `{metadata.get('clang_version', 'unknown')}`; Rust `{metadata.get('rustc_version', 'unknown')}`; Cargo `{metadata.get('cargo_version', 'unknown')}`; CMake `{metadata.get('cmake_version', 'unknown')}`; Make `{metadata.get('make_version', 'unknown')}`.",
            "- The file cache is warm after verification. The runner does not pin processes to a CPU or flush the page cache.",
            "- The target changes the B64Z build. Peer binaries keep their native build and runtime dispatch settings.",
            "",
            "## Files",
            "",
            "[`measurements.tsv`](measurements.tsv) contains the measured rows. [`summary.tsv`](summary.tsv) contains the values used by the table and figures.",
            "",
        ]
    )
    return "\n".join(lines)


def render(target: Target, *, figures_only: bool = False) -> None:
    if not figures_only:
        require_clean_worktree("write a benchmark report")
    target_dir = target.directory
    metadata, rows = read_measurements(target_dir / "measurements.tsv")
    summary = build_summary(rows)
    render_figures(target, rows, summary)
    if figures_only:
        return
    write_summary(target_dir / "summary.tsv", summary)
    report = report_text(target, metadata, rows, summary)
    temporary = target_dir / f".README.md.{os.getpid()}.tmp"
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(target_dir / "README.md")


def run(arguments: argparse.Namespace) -> None:
    target = TARGETS[arguments.target]
    if not arguments.skip_benchmarks:
        require_clean_worktree("measure")
    cases = discover_cases()
    require_files(target)
    generated = prepare_inputs(cases)
    if not arguments.skip_verify:
        print("verifying canonical bytes before timing")
        print(verify(target, cases))
    else:
        print("verification skipped by request")
    if not arguments.skip_benchmarks:
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

    build_parser = commands.add_parser("build", help="build one B64Z benchmark target")
    build_parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    build_parser.set_defaults(handler=build_target)

    render_parser = commands.add_parser(
        "render", help="render a report from measurements.tsv"
    )
    render_parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    render_parser.add_argument(
        "--figures-only", action="store_true", help="redraw SVGs from retained measurements without rewriting report tables or metadata"
    )
    render_parser.set_defaults(handler=lambda args: render(TARGETS[args.target], figures_only=args.figures_only))
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
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
