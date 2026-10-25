#!/usr/bin/env python3
"""Cross-platform PyInstaller build for xarrtools (the single source of truth for build.sh/.ps1/.bat).

Run with the project's virtualenv Python, e.g. ``.venv/bin/python build.py``. The build.* wrappers
make sure the environment exists (via init.*) and then call this script.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent
TEMPLATES = "web/templates"


def build_settings(platform: Optional[str] = None, cache_dir: Optional[str] = None) -> dict:
    """Returns the per-OS icon, data separator and output binary path."""
    platform = platform or sys.platform
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
    return {"icon": icon, "separator": sep, "binary": binary, "workpath": workpath}


def pyinstaller_args(settings: dict) -> List[str]:
    args = ["--onefile", "--name", "xarrtools", f"--icon={settings['icon']}",
            "--add-data", f"{TEMPLATES}{settings['separator']}{TEMPLATES}"]
    if settings["workpath"]:
        args += ["--workpath", settings["workpath"]]
    return args + ["main.py"]


def ensure_pyinstaller() -> None:
    """Installs the dev/build requirements into the active environment if PyInstaller is missing."""
    if importlib.util.find_spec("PyInstaller") is not None:
        return
    print("PyInstaller not found; installing requirements-dev.txt ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")])


def main() -> int:
    os.chdir(ROOT)
    print("Compiling xarrtools to a single executable...")
    ensure_pyinstaller()
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
