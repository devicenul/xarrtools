#!/usr/bin/env bash
# ==============================================================================
# xarrtools Cross-Platform Unix Initialization Script (Linux / macOS / Android VM)
# ==============================================================================
# Sets up the Python virtual environment (with automatic $HOME/.cache ext4
# fallback on Android/virtiofs/FUSE shared storage), installs runtime and
# test/development dependencies, creates .env from .env.example, and initializes
# the local SQLite database schema.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ENV_ONLY=0
SKIP_DEPS=0
QUIET=0

for arg in "$@"; do
    case "$arg" in
        --env-only)
            ENV_ONLY=1
            ;;
        --skip-deps)
            SKIP_DEPS=1
            ;;
        --quiet|-q)
            QUIET=1
            ;;
    esac
done

log_init() {
    if [ "$QUIET" -eq 0 ]; then
        echo "$@"
    fi
}

compute_path_hash() {
    local phys_path
    phys_path="$(pwd -P)"
    phys_path="${phys_path/#\/storage\/emulated\/10/\/mnt\/shared}"
    if command -v sha1sum >/dev/null 2>&1; then
        printf "%s\n" "$phys_path" | sha1sum | cut -c1-8
    elif command -v shasum >/dev/null 2>&1; then
        printf "%s\n" "$phys_path" | shasum -a 1 | cut -c1-8
    else
        printf "%s\n" "$phys_path" | cksum | cut -d' ' -f1
    fi
}

# 1. Locate Python 3 interpreter
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    if python -c 'import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)' 2>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "[Error] Python 3 is required, but 'python' points to Python 2." >&2
        exit 1
    fi
else
    echo "[Error] Python 3 is not installed or not in your PATH." >&2
    echo "Please install Python 3 and try again." >&2
    exit 1
fi

# 2. Clean up broken local .venv if present (e.g., failed symlink creation on FUSE/virtiofs)
if [ -d "$REPO_ROOT/.venv" ] && [ ! -x "$REPO_ROOT/.venv/bin/python" ] && [ ! -f "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
    if [ "$ENV_ONLY" -eq 0 ]; then
        echo "[Init] Removing incomplete local .venv directory..."
    fi
    rm -rf "$REPO_ROOT/.venv"
fi

# 3. Determine whether workspace is on shared/FUSE/virtiofs storage without symlink support
USE_EXT4_CACHE=0
PHYS_PWD="$(pwd -P)"

case "$PHYS_PWD" in
    /storage/emulated/*|/mnt/shared/*)
        USE_EXT4_CACHE=1
        ;;
esac

if [ "$USE_EXT4_CACHE" -eq 0 ] && command -v df >/dev/null 2>&1; then
    FS_TYPE="$(df -T "$REPO_ROOT" 2>/dev/null | awk 'NR==2 {print $2}' || true)"
    case "$FS_TYPE" in
        virtiofs|fuse|fuse.*|fuseblk)
            USE_EXT4_CACHE=1
            ;;
    esac
fi

if [ "$USE_EXT4_CACHE" -eq 0 ]; then
    TEST_LINK="$REPO_ROOT/.venv_symlink_probe_$$"
    if ! ln -s "$REPO_ROOT" "$TEST_LINK" 2>/dev/null; then
        USE_EXT4_CACHE=1
    fi
    rm -f "$TEST_LINK" 2>/dev/null || true
fi

if [ -n "${XARRTOOLS_VENV_DIR:-}" ]; then
    VENV_DIR="$XARRTOOLS_VENV_DIR"
    PROJECT_CACHE_DIR="${PROJECT_CACHE_DIR:-$HOME/.cache/projects/$(basename "$REPO_ROOT")-$(compute_path_hash)}"
elif [ "$USE_EXT4_CACHE" -eq 1 ]; then
    PROJECT_CACHE_DIR="$HOME/.cache/projects/$(basename "$REPO_ROOT")-$(compute_path_hash)"
    VENV_DIR="$PROJECT_CACHE_DIR/venv"
    export PYTHONPYCACHEPREFIX="$PROJECT_CACHE_DIR/pycache"
    export PIP_CACHE_DIR="$PROJECT_CACHE_DIR/pip"
    export COVERAGE_FILE="${COVERAGE_FILE:-$PROJECT_CACHE_DIR/.coverage}"
else
    PROJECT_CACHE_DIR=""
    VENV_DIR="$REPO_ROOT/.venv"
fi

export PROJECT_CACHE_DIR
export VENV_DIR
export PYTHON_CMD

if [ "$ENV_ONLY" -eq 1 ]; then
    return 0 2>/dev/null || exit 0
fi

log_init "=================================================="
log_init "  xarrtools Project Initialization (Unix)"
log_init "=================================================="
log_init "[Init] Project directory : $REPO_ROOT"
log_init "[Init] Python executable : $($PYTHON_CMD --version 2>&1)"
log_init "[Init] Virtualenv path   : $VENV_DIR"

if [ -n "$PROJECT_CACHE_DIR" ]; then
    mkdir -p "$PROJECT_CACHE_DIR" "${PYTHONPYCACHEPREFIX:-$PROJECT_CACHE_DIR/pycache}" "${PIP_CACHE_DIR:-$PROJECT_CACHE_DIR/pip}"
fi

# 4. Create virtual environment if needed
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[Init] Creating Python virtual environment at $VENV_DIR..."
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null; then
        echo "[Init] Standard venv symlink creation failed; retrying with --copies..."
        rm -rf "$VENV_DIR"
        "$PYTHON_CMD" -m venv --copies "$VENV_DIR"
    fi
fi

# 5. Install runtime and test/development dependencies
if [ "$SKIP_DEPS" -eq 0 ]; then
    log_init "[Init] Installing development dependencies from pyproject.toml..."
    "$VENV_DIR/bin/pip" install -e ".[dev]"
fi

# 5b. Install frontend build dependencies (TypeScript)
WEB_DIR="$REPO_ROOT/src/xarrtools/web"
if [ "$SKIP_DEPS" -eq 0 ] && [ -f "$WEB_DIR/package.json" ]; then
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "[Error] Node.js (npm) is required to build the frontend: install it from https://nodejs.org" >&2
        exit 1
    fi
    log_init "[Init] Installing frontend dependencies from package.json..."
    if [ -n "$PROJECT_CACHE_DIR" ]; then
        npm_config_cache="$PROJECT_CACHE_DIR/npm" npm --prefix "$WEB_DIR" install --no-audit --no-fund 2>/dev/null || npm_config_cache="$PROJECT_CACHE_DIR/npm" npm --prefix "$WEB_DIR" install --no-audit --no-fund --no-bin-links
    else
        npm --prefix "$WEB_DIR" install --no-audit --no-fund 2>/dev/null || npm --prefix "$WEB_DIR" install --no-audit --no-fund --no-bin-links
    fi
    if [ -f "$WEB_DIR/node_modules/typescript/bin/tsc" ] && [ ! -e "$WEB_DIR/node_modules/.bin/tsc" ]; then
        mkdir -p "$WEB_DIR/node_modules/.bin"
        printf '#!/bin/sh\nexec node "$(dirname "$0")/../typescript/bin/tsc" "$@"\n' > "$WEB_DIR/node_modules/.bin/tsc"
        chmod +x "$WEB_DIR/node_modules/.bin/tsc" 2>/dev/null || true
    fi
    log_init "[Init] Compiling the TypeScript frontend (src/xarrtools/web/static/dist)..."
    npm --prefix "$WEB_DIR" run build --silent
fi

# 6. Generate .env configuration from template if missing
if [ ! -f "$REPO_ROOT/.env" ]; then
    if [ -f "$REPO_ROOT/.env.example" ]; then
        echo "[Init] Creating .env configuration file from .env.example..."
        cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
        echo "[Note] Default .env created. You can configure Radarr/Sonarr credentials in .env or via the Web UI Settings."
    else
        echo "[Warning] .env.example not found; skipping .env creation."
    fi
else
    log_init "[Init] Existing .env configuration found."
fi

# 7. Initialize SQLite database schema and prune expired cache
log_init "[Init] Initializing SQLite database schema (xarrtools.db)..."
PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$VENV_DIR/bin/python" -c "from xarrtools.core.db import init_db, clean_expired_cache; init_db(); clean_expired_cache()"

log_init "=================================================="
log_init "  [Success] xarrtools initialization complete!"
log_init "=================================================="
