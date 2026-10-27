#!/usr/bin/env python3
"""Cross-platform PyInstaller build for xarrtools (the single source of truth for build.sh/.ps1/.bat).

Run with the project's virtualenv Python, e.g. ``.venv/bin/python scripts/build.py``. The build.* wrappers
make sure the environment exists (via init.*) and then call this script.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = "web/templates"


def build_settings(
    platform: Optional[str] = None,
    cache_dir: Optional[str] = None,
    dist_exists: Optional[bool] = None
) -> Dict[str, Any]:
    """Determine the platform-specific icon, data separator, and output binary path.

    Args:
        platform: Target platform identifier (defaults to sys.platform).
        cache_dir: Optional directory to store intermediate PyInstaller build files.
        dist_exists: Override flag indicating if compiled web assets exist.

    Returns:
        Dictionary containing icon path, separator, binary Path, workpath, and dist_exists.
    """
    platform = platform or sys.platform
    # Configure platform-specific icon format and output binary naming
    if platform.startswith("win"):
        icon, binary = f"{TEMPLATES}/favicon.ico", Path("dist") / "xarrtools.exe"
        sep = ";"
    elif platform == "darwin":
        icon, binary = f"{TEMPLATES}/favicon.icns", Path("dist") / "xarrtools"
        sep = ":"
    else:
        icon, binary = f"{TEMPLATES}/favicon.png", Path("dist") / "xarrtools"
        sep = ":"
    workpath = str(Path(cache_dir) / "pyinstaller-build") if cache_dir else None
    if dist_exists is None:
        dist_exists = (ROOT / "web" / "static" / "dist").is_dir()
    return {"icon": icon, "separator": sep, "binary": binary, "workpath": workpath, "dist_exists": dist_exists}


def pyinstaller_args(settings: Dict[str, Any], dist_exists: Optional[bool] = None) -> List[str]:
    """Construct command-line arguments for PyInstaller.

    Args:
        settings: Build settings dictionary from build_settings().
        dist_exists: Optional override flag for static asset directory presence.

    Returns:
        List of command-line flags and arguments to pass to PyInstaller.
    """
    args = [
        "--onefile",
        "--name", "xarrtools",
        f"--icon={settings['icon']}",
        "--collect-submodules", "webview",
        "--add-data", f"{TEMPLATES}{settings['separator']}{TEMPLATES}"
    ]
    has_dist = dist_exists if dist_exists is not None else settings.get("dist_exists", False)
    if has_dist:
        args += ["--add-data", f"web/static/dist{settings['separator']}web/static/dist"]
    if settings.get("workpath"):
        args += ["--workpath", settings["workpath"]]
    return args + ["main.py"]


def stamp_version(version: Optional[str] = None) -> Optional[str]:
    """Writes core/_version.py if a version is specified via argument or XARRTOOLS_VERSION."""
    ver = version or os.environ.get("XARRTOOLS_VERSION")
    if not ver:
        return None
    ver_clean = ver.lstrip("v")
    version_file = ROOT / "core" / "_version.py"
    version_file.write_text(f'"""Stamped release version."""\n__version__ = "{ver_clean}"\n', encoding="utf-8")
    print(f"Stamped application version: {ver_clean}")
    return ver_clean


def ensure_pyinstaller() -> None:
    """Verify PyInstaller is installed in the active environment, installing requirements-dev.txt if missing."""
    if importlib.util.find_spec("PyInstaller") is not None:
        return
    print("PyInstaller not found; installing requirements-dev.txt ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")])


def build_frontend(root: Optional[Path] = None) -> bool:
    """Compile TypeScript and web assets via npm if source files exist.

    Args:
        root: Optional workspace root directory (defaults to ROOT).

    Returns:
        True if frontend compiled successfully or wasn't needed, False on failure.
    """
    base = Path(root) if root is not None else ROOT
    src_dir = base / "web" / "static" / "src"
    if not src_dir.is_dir():
        return True
    has_sources = any(p.is_file() and p.suffix in {".ts", ".js", ".tsx"} for p in src_dir.rglob("*"))
    if not has_sources:
        return True

    npm = shutil.which("npm")
    if not npm:
        print("[Error] Node.js (npm) is required to build the frontend: install it from https://nodejs.org", file=sys.stderr)
        return False

    node_modules = base / "node_modules"
    if not node_modules.is_dir():
        print("Installing frontend dependencies (npm install)...")
        res = subprocess.call([npm, "install", "--no-audit", "--no-fund"], cwd=str(base))
        if res != 0:
            # Fall back to --no-bin-links for environments with limited symlink support (e.g. Android shared mount)
            res = subprocess.call([npm, "install", "--no-audit", "--no-fund", "--no-bin-links"], cwd=str(base))
        if res != 0:
            print("[Error] npm install failed.", file=sys.stderr)
            return False

    # Create tsc launcher wrapper script if missing due to --no-bin-links
    bin_dir = node_modules / ".bin"
    tsc_bin = bin_dir / "tsc"
    tsc_src = node_modules / "typescript" / "bin" / "tsc"
    if tsc_src.is_file() and not tsc_bin.exists():
        bin_dir.mkdir(parents=True, exist_ok=True)
        tsc_bin.write_text('#!/bin/sh\nexec node "$(dirname "$0")/../typescript/bin/tsc" "$@"\n', encoding="utf-8")
        try:
            tsc_bin.chmod(0o755)
        except OSError:
            pass

    print("Building frontend (npm run build)...")
    if subprocess.call([npm, "run", "build"], cwd=str(base)) != 0:
        print("[Error] npm run build failed.", file=sys.stderr)
        return False
    return True


def main(argv: Optional[List[str]] = None) -> int:
    """Execute the PyInstaller build pipeline and return exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    version = None
    if "--version" in raw_args:
        idx = raw_args.index("--version")
        if idx + 1 < len(raw_args):
            version = raw_args[idx + 1]
    stamp_version(version)
    os.chdir(ROOT)
    if not build_frontend(ROOT):
        return 1
    print("Compiling xarrtools to a single executable...")
    ensure_pyinstaller()
    # Cache directory can be overridden via environment variables (e.g. on Android VM)
    cache_dir = os.environ.get("XARRTOOLS_PROJECT_CACHE_DIR") or os.environ.get("PROJECT_CACHE_DIR")
    settings = build_settings(cache_dir=cache_dir)
    cmd = [sys.executable, "-m", "PyInstaller"] + pyinstaller_args(settings)
    if subprocess.call(cmd) != 0:
        print("\n[Error] Compilation failed.", file=sys.stderr)
        return 1
    print(f"\n[Success] Compilation complete!\nBinary available at: {settings['binary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

