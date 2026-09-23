"""Peer commands and version records for benchmark verification and reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_ROOT = ROOT / "tools" / "bin"


@dataclass(frozen=True)
class Peer:
    id: str
    label: str
    executable_name: str
    version: str
    encode_args: tuple[str, ...]
    decode_args: tuple[str, ...]
    modes: tuple[str, ...]

    @property
    def executable(self) -> Path:
        return BIN_ROOT / self.executable_name


PEERS = (
    Peer(
        "aklomp",
        "Aklomp",
        "aklomp-base64",
        "aklomp/base64 bf058e571ac5002b75b03fed38e33ed4e8d45eff, AVX2_CFLAGS=-mavx2 upstream make",
        ("--wrap=0",),
        ("--decode", "--no-strip-newlines"),
        ("encode-streaming", "decode-streaming"),
    ),
    Peer(
        "simdutf",
        "simdutf",
        "simdutf-fastbase64",
        "simdutf v9.2.0 8abc1d7a466bc882c2d72e1effd8661492db257c, Release CMake and direct C++ adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "coreutils",
        "GNU coreutils",
        "coreutils-base64",
        "GNU coreutils base64 9.11, local build flags -g -O2",
        ("-w", "0"),
        ("--decode",),
        ("encode-streaming", "decode-streaming"),
    ),
    Peer(
        "turbo",
        "Turbo-Base64",
        "turbo-base64",
        "Turbo-Base64 d9e584363280055ba6355938a48dc3711183f50f, upstream make and direct C adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "rust-base64",
        "Rust base64",
        "rust-base64-simd",
        "Rust base64 crate 0.23.1, Simd engine, Cargo release fat LTO",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "rust-simd",
        "Rust base64-simd",
        "rust-base64-simd-crate",
        "Rust base64-simd crate 0.8.0, Cargo release fat LTO",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
    Peer(
        "zig-std",
        "Zig std.base64",
        "zig-std-base64",
        "Zig 0.16.0 std.base64, ReleaseFast -Dcpu=native adapter",
        (),
        ("--decode",),
        ("encode-memory", "decode-memory"),
    ),
)
PEER_BY_ID = {peer.id: peer for peer in PEERS}


def peer_command(peer: Peer, mode: str, input_path: Path) -> list[str]:
    args = peer.decode_args if mode.startswith("decode-") else peer.encode_args
    return [str(peer.executable), *args, str(input_path)]


def aklomp_command(input_path: Path, *, decode: bool = False) -> list[str]:
    mode = "decode-streaming" if decode else "encode-streaming"
    return peer_command(PEER_BY_ID["aklomp"], mode, input_path)
