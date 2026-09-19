#!/usr/bin/env bash
# Run one of the two retained Linux x86-64 benchmark reports.
#
# Usage:
#   bash bench/run.sh --target linux-x86-avx2
#   bash bench/run.sh --target linux-x86-scalar --runs 20 --warmup 5
#
# The target wrapper scripts in bench/linux-x86-avx2/ and
# bench/linux-x86-scalar/ pass the target name for the common invocation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

TARGET=""
REPORT_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            [[ $# -ge 2 ]] || { echo "error: --target needs a value" >&2; exit 2; }
            TARGET="$2"
            shift 2
            ;;
        --runs|--warmup|--duration)
            [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; exit 2; }
            REPORT_ARGS+=("$1" "$2")
            shift 2
            ;;
        --skip-verify|--skip-benchmarks|--skip-report)
            REPORT_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            exit 2
            ;;
    esac
done

case "$TARGET" in
    linux-x86-avx2)
        CPU_TARGET="haswell"
        EXPECTED_BACKEND="avx2"
        ;;
    linux-x86-scalar)
        CPU_TARGET="x86_64"
        EXPECTED_BACKEND="scalar"
        ;;
    *)
        echo "error: choose --target linux-x86-avx2 or linux-x86-scalar" >&2
        exit 2
        ;;
esac

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "error: this runner requires Linux x86_64" >&2
    exit 1
fi

if [[ "$TARGET" == "linux-x86-avx2" && ! -r /proc/cpuinfo ]]; then
    echo "error: cannot inspect /proc/cpuinfo for the AVX2 target" >&2
    exit 1
fi

if [[ "$TARGET" == "linux-x86-avx2" ]] && ! grep -qE '(^|[[:space:]])avx2([[:space:]]|$)' /proc/cpuinfo; then
    echo "error: this CPU does not report AVX2" >&2
    exit 1
fi

command -v zig >/dev/null || { echo "error: zig is not on PATH" >&2; exit 1; }
command -v gnuplot >/dev/null || { echo "error: gnuplot is not on PATH" >&2; exit 1; }

TARGET_DIR="$SCRIPT_DIR/$TARGET"
echo "building $TARGET with zig -Dcpu=$CPU_TARGET -Doptimize=ReleaseFast -Dstrip=true"
(cd "$PROJECT_ROOT" && zig build -Dcpu="$CPU_TARGET" -Doptimize=ReleaseFast -Dstrip=true --prefix "$TARGET_DIR")

B64Z_BINARY="$TARGET_DIR/bin/custom-base64"
if [[ ! -x "$B64Z_BINARY" ]]; then
    echo "error: build did not produce $B64Z_BINARY" >&2
    exit 1
fi

B64Z_VERSION="$("$B64Z_BINARY" --version)"
if [[ "$B64Z_VERSION" != *"backend=$EXPECTED_BACKEND"* || "$B64Z_VERSION" != *"optimize=ReleaseFast"* ]]; then
    echo "error: unexpected B64Z build: $B64Z_VERSION" >&2
    exit 1
fi

PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$SCRIPT_DIR/report.py" run --target "$TARGET" "${REPORT_ARGS[@]}"
