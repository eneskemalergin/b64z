#!/usr/bin/env bash
# Read the package version, extract its changelog entry, or build and test a release archive.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

version=$(sed -n 's/^    \.version = "\([^"]*\)",$/\1/p' build.zig.zon)
if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    printf 'error: build.zig.zon must declare one major.minor.patch version\n' >&2
    exit 1
fi

case "${1:-}" in
    version)
        printf '%s\n' "$version"
        ;;
    notes)
        tag="${2:-v$version}"
        if [[ "$tag" != "v$version" ]]; then
            printf 'error: tag %s does not match CLI version v%s\n' "$tag" "$version" >&2
            exit 1
        fi
        awk -v version="$version" '
            /^## / {
                if (found) exit
                found = ($2 == "[" version "]")
                next
            }
            found {
                print
                if ($0 ~ /[^[:space:]]/ && $0 !~ /^#/) nonempty = 1
            }
            END { if (!found || !nonempty) exit 1 }
        ' CHANGELOG.md || {
            printf 'error: CHANGELOG.md needs a nonempty [%s] entry\n' "$version" >&2
            exit 1
        }
        ;;
    package)
        backend="${2:?usage: release.sh package source|scalar|avx2 OUTPUT_DIRECTORY}"
        output="${3:?usage: release.sh package source|scalar|avx2 OUTPUT_DIRECTORY}"
        case "$backend" in
            source) ;;
            scalar) cpu=x86_64 ;;
            avx2) cpu=haswell ;;
            *) printf 'error: unknown backend %s\n' "$backend" >&2; exit 1 ;;
        esac
        name="b64z-$version-linux-x86-$backend"
        if [[ "$backend" == source ]]; then
            name="b64z-$version-source"
        fi
        mkdir -p "$output"
        archive="$(cd "$output" && pwd)/$name.tar.gz"
        if [[ -e "$archive" ]]; then
            printf 'error: archive already exists: %s\n' "$archive" >&2
            exit 1
        fi
        work=$(mktemp -d "${TMPDIR:-/tmp}/b64z-release.XXXXXX")
        trap 'rm -rf -- "$work"' EXIT
        if [[ "$backend" == source ]]; then
            zig build source --prefix "$work/install"
            mkdir "$work/consumer"
            (
                cd "$work/consumer"
                zig init --minimal
                # Fetch only an archive, with its source, consumer, and cache in separate directories.
                zig fetch --global-cache-dir "$work/package-cache" --save=b64z "$work/install/$name.tar.gz"
                cat > build.zig <<'ZIG'
//! Checks the public module from the fetched source package.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const dependency = b.dependency("b64z", .{ .target = target, .optimize = optimize });
    const exe = b.addExecutable(.{
        .name = "package-check",
        .root_module = b.createModule(.{
            .root_source_file = b.path("main.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{.{ .name = "base64", .module = dependency.module("base64") }},
        }),
    });
    b.installArtifact(exe);
}
ZIG
                cat > main.zig <<'ZIG'
//! Converts bytes using only the fetched Base64 module.
const std = @import("std");
const base64 = @import("base64");

pub fn main() !void {
    var encoded: [8]u8 = undefined;
    const encoded_len = try base64.encode("hello", &encoded);
    if (!std.mem.eql(u8, encoded[0..encoded_len], "aGVsbG8=")) return error.InvalidEncoding;
    var decoded: [5]u8 = undefined;
    const decoded_len = try base64.decode(encoded[0..encoded_len], &decoded);
    if (!std.mem.eql(u8, decoded[0..decoded_len], "hello")) return error.InvalidDecoding;
}
ZIG
                zig build -Dcpu=x86_64 -Doptimize=ReleaseFast --cache-dir "$work/consumer-cache" \
                    --global-cache-dir "$work/package-cache" --prefix "$work/consumer-install"
                "$work/consumer-install/bin/package-check"
                test ! -e "$work/consumer-install/bin/custom-base64"
            )
            mv "$work/install/$name.tar.gz" "$archive"
            printf 'Tested %s\n' "$archive"
            exit 0
        fi
        zig build -Dtarget=x86_64-linux -Dcpu="$cpu" -Doptimize=ReleaseFast -Dstrip=true --prefix "$work/install"
        mkdir "$work/$name" "$work/unpacked"
        cp "$work/install/bin/custom-base64" LICENSE THIRD_PARTY_NOTICES.md "$work/$name/"
        tar -czf "$work/$name.tar.gz" -C "$work" "$name"
        tar -xzf "$work/$name.tar.gz" -C "$work/unpacked"

        binary="$work/unpacked/$name/custom-base64"
        actual=$(env -i PATH=/usr/bin:/bin "$binary" --version 2> "$work/stderr")
        printf '%s\n' "$actual"
        test "$actual" = "custom-base64 $version backend=$backend optimize=ReleaseFast target=x86_64"
        test ! -s "$work/stderr"
        cmp LICENSE "$work/unpacked/$name/LICENSE"
        cmp THIRD_PARTY_NOTICES.md "$work/unpacked/$name/THIRD_PARTY_NOTICES.md"
        printf 'foo\000\377\001bar\n' > "$work/input"
        base64 --wrap=0 "$work/input" > "$work/expected"
        for mode in memory streaming; do
            env -i PATH=/usr/bin:/bin "$binary" --mode "encode-$mode" "$work/input" > "$work/encoded" 2> "$work/stderr"
            test ! -s "$work/stderr"
            cmp "$work/expected" "$work/encoded"
            env -i PATH=/usr/bin:/bin "$binary" --mode "decode-$mode" "$work/expected" > "$work/decoded" 2> "$work/stderr"
            test ! -s "$work/stderr"
            cmp "$work/input" "$work/decoded"
        done
        mv "$work/$name.tar.gz" "$archive"
        printf 'Tested %s\n' "$archive"
        ;;
    *)
        printf 'usage: release.sh version | notes [TAG] | package source|scalar|avx2 OUTPUT_DIRECTORY\n' >&2
        exit 2
        ;;
esac
