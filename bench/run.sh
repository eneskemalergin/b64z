#!/usr/bin/env bash
# Run one retained Linux x86-64 benchmark report.
#
# Usage:
#   bash bench/run.sh --target linux-x86-avx2
#   bash bench/run.sh --target linux-x86-scalar --runs 20 --warmup 5

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""
REPORT_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            [[ $# -ge 2 ]] || { echo "error: --target needs a value" >&2; exit 2; }
            TARGET="$2"
            shift 2
            ;;
        --target=*)
            TARGET="${1#*=}"
            shift
            ;;
        -h|--help)
            exec "${PYTHON:-python3}" "$SCRIPT_DIR/report.py" run --help
            ;;
        *)
            REPORT_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$TARGET" ]]; then
    echo "error: choose --target linux-x86-avx2 or linux-x86-scalar" >&2
    exit 2
fi

PYTHON="${PYTHON:-python3}"
"$PYTHON" "$SCRIPT_DIR/report.py" build --target "$TARGET"
exec "$PYTHON" "$SCRIPT_DIR/report.py" run --target "$TARGET" "${REPORT_ARGS[@]}"
