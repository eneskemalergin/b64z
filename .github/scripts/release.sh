#!/usr/bin/env bash
# Read the CLI version, extract its changelog entry, or build and test a release archive.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

version=$(sed -n 's/^const VERSION = "\([^"]*\)";$/\1/p' src/main.zig)
if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    printf 'error: src/main.zig must declare one major.minor.patch VERSION\n' >&2
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
        backend="${2:?usage: release.sh package scalar|avx2 OUTPUT_DIRECTORY}"
        output="${3:?usage: release.sh package scalar|avx2 OUTPUT_DIRECTORY}"
        case "$backend" in
            scalar) cpu=x86_64 ;;
            avx2) cpu=haswell ;;
            *) printf 'error: unknown backend %s\n' "$backend" >&2; exit 1 ;;
        esac
        name="b64z-$version-linux-x86-$backend"
        mkdir -p "$output"
        archive="$(cd "$output" && pwd)/$name.tar.gz"
        if [[ -e "$archive" ]]; then
            printf 'error: archive already exists: %s\n' "$archive" >&2
            exit 1
        fi
        work=$(mktemp -d "${TMPDIR:-/tmp}/b64z-release.XXXXXX")
        trap 'rm -rf -- "$work"' EXIT
        zig build -Dtarget=x86_64-linux -Dcpu="$cpu" -Doptimize=ReleaseFast -Dstrip=true --prefix "$work/install"
        mkdir "$work/$name" "$work/unpacked"
        cp "$work/install/bin/custom-base64" LICENSE "$work/$name/"
        tar -czf "$work/$name.tar.gz" -C "$work" "$name"
        tar -xzf "$work/$name.tar.gz" -C "$work/unpacked"

        binary="$work/unpacked/$name/custom-base64"
        actual=$(env -i PATH=/usr/bin:/bin "$binary" --version 2> "$work/stderr")
        printf '%s\n' "$actual"
        test "$actual" = "custom-base64 $version backend=$backend optimize=ReleaseFast target=x86_64"
        test ! -s "$work/stderr"
        cmp LICENSE "$work/unpacked/$name/LICENSE"
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
        printf 'usage: release.sh version | notes [TAG] | package scalar|avx2 OUTPUT_DIRECTORY\n' >&2
        exit 2
        ;;
esac
