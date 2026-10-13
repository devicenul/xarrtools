#!/usr/bin/env bash
# ==============================================================================
# xarrtools Compiler Script (Unix: Linux / macOS / Android VM)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

echo "Ensuring PyInstaller is installed in the virtual environment..."
"$VENV_DIR/bin/pip" install pyinstaller

# 2. Detect OS to set the appropriate icon format
OS_NAME="$(uname -s)"
if [ "$OS_NAME" = "Darwin" ]; then
    ICON_FILE="web/templates/favicon.icns"
else
    ICON_FILE="web/templates/favicon.png"
fi

# 3. Redirect intermediate PyInstaller workpath to local ext4 cache when available
WORKPATH_ARGS=()
if [ -n "${PROJECT_CACHE_DIR:-}" ]; then
    WORKPATH_ARGS=(--workpath "$PROJECT_CACHE_DIR/pyinstaller-build")
fi

echo ""
echo "Compiling xarrtools to a single executable..."
if "$VENV_DIR/bin/pyinstaller" --onefile --name xarrtools --icon="$ICON_FILE" --add-data "web/templates:web/templates" "${WORKPATH_ARGS[@]}" main.py; then
    echo ""
    echo "[Success] Compilation complete!"
    echo "Binary available at: dist/xarrtools"
else
    echo ""
    echo "[Error] Compilation failed." >&2
    exit 1
fi
