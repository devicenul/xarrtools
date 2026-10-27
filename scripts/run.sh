#!/usr/bin/env bash
# ==============================================================================
# xarrtools Unix Auto-Startup Launcher (Linux / macOS / Android VM)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=================================================="
echo "  xarrtools Unix Auto-Startup Launcher"
echo "=================================================="

# 1. Load environment paths from init.sh
# shellcheck source=./init.sh
source "$SCRIPT_DIR/init.sh" --env-only

# 2. Run full initialization if environment or dependencies are missing
if [ ! -x "$VENV_DIR/bin/python" ] || [ ! -f "$REPO_ROOT/.env" ] || [ ! -f "$REPO_ROOT/xarrtools.db" ] || \
   ! "$VENV_DIR/bin/python" -c "import flask, requests, bs4, rich, dotenv, waitress, defusedxml" >/dev/null 2>&1; then
    bash "$SCRIPT_DIR/init.sh"
else
    bash "$SCRIPT_DIR/init.sh" --skip-deps --quiet
fi

# 3. Launch the application, forwarding all CLI arguments (e.g., --cli, --server, --gui, --debug)
echo ""
echo "Booting xarrtools..."
echo "--------------------------------------------------"
"$VENV_DIR/bin/python" main.py "$@"
echo "--------------------------------------------------"
echo "Application closed."
