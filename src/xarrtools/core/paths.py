"""Data and configuration path resolution for xarrtools.

Determines the application data directory where xarrtools.db, .env, posters/, and logs/
are stored. Precedence order:
1. PyInstaller frozen binary -> sys.executable parent directory.
2. XARRTOOLS_CONFIG_DIR environment variable -> explicit directory override.
3. Source checkout or editable install -> repository root folder.
4. User application data directory -> platform-specific standard location:
   - macOS: ~/Library/Application Support/xarrtools
   - Windows: %APPDATA%/xarrtools (fallback: ~/AppData/Roaming/xarrtools)
   - Linux/other: $XDG_DATA_HOME/xarrtools (fallback: ~/.local/share/xarrtools)
"""
import os
import sys
from pathlib import Path
from typing import Optional


def _detect_source_checkout(pkg_dir: Optional[Path] = None) -> Optional[Path]:
    """Detects if pkg_dir is running from a source checkout or editable install.

    Returns the repository root Path if pkg_dir is directly inside <repo>/src/xarrtools,
    or None if pkg_dir is installed inside site-packages, dist-packages, or another location.

    Guards against misdetecting site-packages installs as source checkouts, even when
    the virtual environment resides within a repository or parent directory containing
    a pyproject.toml.
    """
    if pkg_dir is None:
        pkg_dir = Path(__file__).resolve().parent.parent

    try:
        resolved_pkg = pkg_dir.resolve()
    except OSError:
        resolved_pkg = pkg_dir

    # Guard 1: Any installation inside site-packages or dist-packages is never a source checkout
    if any(part in ("site-packages", "dist-packages") for part in resolved_pkg.parts):
        return None

    # Check standard repository layout: <repo>/src/xarrtools
    src_dir = resolved_pkg.parent
    if src_dir.name == "src":
        candidate_root = src_dir.parent
        pyproject = candidate_root / "pyproject.toml"
        expected_src_pkg = candidate_root / "src" / "xarrtools"
        if pyproject.is_file() and expected_src_pkg.is_dir():
            try:
                if expected_src_pkg.resolve() == resolved_pkg:
                    return candidate_root.resolve()
            except OSError:
                if expected_src_pkg == resolved_pkg:
                    return candidate_root

    # Walk up parent directories looking for pyproject.toml next to src/xarrtools,
    # strictly verifying that <candidate>/src/xarrtools resolves to this executing package.
    for parent in resolved_pkg.parents:
        if any(part in ("site-packages", "dist-packages") for part in parent.parts):
            break
        pyproject = parent / "pyproject.toml"
        expected_src_pkg = parent / "src" / "xarrtools"
        if pyproject.is_file() and expected_src_pkg.is_dir():
            try:
                if expected_src_pkg.resolve() == resolved_pkg:
                    return parent.resolve()
            except OSError:
                if expected_src_pkg == resolved_pkg:
                    return parent

    return None


def _get_user_data_dir(platform: Optional[str] = None) -> Path:
    """Returns the platform-specific standard user application data directory.

    Creates the directory and intermediate parents on first use with sensible permissions
    (0o700 on POSIX systems).
    """
    if platform is None:
        platform = sys.platform

    if platform == "darwin":
        # macOS: ~/Library/Application Support/xarrtools
        home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
        data_dir = home / "Library" / "Application Support" / "xarrtools"
    elif platform == "win32" or platform.startswith("win"):
        # Windows: %APPDATA%\xarrtools (fallback ~\AppData\Roaming\xarrtools)
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~"))
            base = home / "AppData" / "Roaming"
        data_dir = base / "xarrtools"
    else:
        # Linux and other POSIX: $XDG_DATA_HOME/xarrtools else ~/.local/share/xarrtools
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base = Path(xdg_data)
        else:
            home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
            base = home / ".local" / "share"
        data_dir = base / "xarrtools"

    data_dir.mkdir(parents=True, exist_ok=True)
    if platform != "win32" and not platform.startswith("win") and os.name != "nt":
        try:
            os.chmod(data_dir, 0o700)
        except OSError:
            pass

    return data_dir.resolve()


def get_data_dir() -> Path:
    """Returns the resolved base data directory for xarrtools persistence and configuration.

    Order of precedence:
    1. PyInstaller frozen binary: directory containing sys.executable.
    2. XARRTOOLS_CONFIG_DIR environment variable: explicitly configured custom directory.
    3. Source checkout or editable install: repository root directory.
    4. Per-user standard application data directory:
       - macOS: ~/Library/Application Support/xarrtools
       - Windows: %APPDATA%\\xarrtools (fallback: ~\\AppData\\Roaming\\xarrtools)
       - Linux/other: $XDG_DATA_HOME/xarrtools (fallback: ~/.local/share/xarrtools)
    """
    # 1. PyInstaller frozen binary
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    # 2. XARRTOOLS_CONFIG_DIR environment variable override
    config_dir_env = os.environ.get("XARRTOOLS_CONFIG_DIR")
    if config_dir_env:
        target = Path(config_dir_env).resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    # 3. Source checkout or editable install
    repo_root = _detect_source_checkout()
    if repo_root is not None:
        return repo_root

    # 4. Fallback to per-user application data directory
    return _get_user_data_dir()
