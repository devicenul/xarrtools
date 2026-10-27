#!/usr/bin/env bash
# ==============================================================================
# xarrtools Compiler Script (Unix: Linux / macOS / Android VM)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=================================================="
echo "  xarrtools Compiler Script (Unix)"
echo "=================================================="

# 1. Load environment paths from init.sh and initialize if needed
# shellcheck source=./init.sh
source "$SCRIPT_DIR/init.sh" --env-only

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[Build] Virtual environment not initialized. Running init.sh first..."
    bash "$SCRIPT_DIR/init.sh"
fi

# 2. Compile (icon/data-path/workpath selection and PyInstaller install live in build.py)
echo ""
if "$VENV_DIR/bin/python" "$SCRIPT_DIR/build.py" "$@"; then
    exit 0
else
    exit 1
fi
