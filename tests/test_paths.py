"""Unit tests for xarrtools.core.paths data directory resolution and precedence."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import xarrtools.core.paths as paths
from xarrtools.core.paths import (
    get_data_dir,
    _detect_source_checkout,
    _get_user_data_dir,
)


def test_frozen_precedence(tmp_path, monkeypatch):
    """sys.frozen takes top precedence, returning the directory of sys.executable."""
    fake_exe_dir = tmp_path / "bin"
    fake_exe_dir.mkdir()
    fake_exe = fake_exe_dir / "xarrtools"
    fake_exe.touch()

    # Even if XARRTOOLS_CONFIG_DIR is set, frozen must win
    monkeypatch.setenv("XARRTOOLS_CONFIG_DIR", str(tmp_path / "ignored_config"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert get_data_dir() == fake_exe_dir.resolve()


def test_config_dir_env_precedence(tmp_path, monkeypatch):
    """XARRTOOLS_CONFIG_DIR takes precedence over source checkout and user data dir."""
    config_dir = tmp_path / "custom_config_dir"
    assert not config_dir.exists()

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("XARRTOOLS_CONFIG_DIR", str(config_dir))

    resolved = get_data_dir()
    assert resolved == config_dir.resolve()
    assert resolved.is_dir()


def test_source_checkout_detection_current_repo():
    """In the current repository development environment, source checkout is detected."""
    repo_root = _detect_source_checkout()
    assert repo_root is not None
    assert (repo_root / "pyproject.toml").is_file()
    assert (repo_root / "src" / "xarrtools").is_dir()


def test_source_checkout_detection_mocked_tree(tmp_path):
    """Simulated standard source tree layout <repo>/src/xarrtools is detected correctly."""
    repo_dir = tmp_path / "my_project"
    repo_dir.mkdir()
    (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    pkg_dir = repo_dir / "src" / "xarrtools"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").touch()

    detected = _detect_source_checkout(pkg_dir)
    assert detected == repo_dir.resolve()


def test_detect_source_checkout_guards_site_packages(tmp_path):
    """Installations inside site-packages or dist-packages must never be detected as source checkouts."""
    site_packages_pkg = tmp_path / "lib" / "python3.12" / "site-packages" / "xarrtools"
    site_packages_pkg.mkdir(parents=True)
    assert _detect_source_checkout(site_packages_pkg) is None

    dist_packages_pkg = tmp_path / "lib" / "python3" / "dist-packages" / "xarrtools"
    dist_packages_pkg.mkdir(parents=True)
    assert _detect_source_checkout(dist_packages_pkg) is None


def test_detect_source_checkout_guards_venv_inside_repo(tmp_path):
    """A virtualenv inside a repo directory must NOT misdetect the parent repo as source checkout."""
    repo_dir = tmp_path / "some_repo"
    repo_dir.mkdir()
    (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (repo_dir / "src" / "xarrtools").mkdir(parents=True)

    # Simulated wheel install into .venv inside that same repo
    venv_pkg = repo_dir / ".venv" / "lib" / "python3.12" / "site-packages" / "xarrtools"
    venv_pkg.mkdir(parents=True)

    assert _detect_source_checkout(venv_pkg) is None


def test_detect_source_checkout_guards_nested_without_matching_src(tmp_path):
    """Even if parent has pyproject.toml and src/xarrtools, an unrelated pkg path must not match."""
    repo_dir = tmp_path / "other_repo"
    repo_dir.mkdir()
    (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (repo_dir / "src" / "xarrtools").mkdir(parents=True)

    # Unrelated package path not inside site-packages
    foreign_pkg = repo_dir / "custom_install" / "xarrtools"
    foreign_pkg.mkdir(parents=True)

    assert _detect_source_checkout(foreign_pkg) is None


def test_user_data_dir_macos(tmp_path, monkeypatch):
    """macOS resolves to ~/Library/Application Support/xarrtools."""
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _get_user_data_dir("darwin")
    expected = (tmp_path.resolve() / "Library" / "Application Support" / "xarrtools").resolve()
    assert result == expected
    assert result.is_dir()
    # Check permissions are sensible (0o700 on POSIX)
    if os.name == "posix":
        assert (result.stat().st_mode & 0o777) == 0o700


def test_user_data_dir_windows_appdata(tmp_path, monkeypatch):
    """Windows resolves to %APPDATA%\\xarrtools when APPDATA is defined."""
    fake_appdata = tmp_path / "AppData" / "Roaming"
    fake_appdata.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    result = _get_user_data_dir("win32")
    expected = (fake_appdata / "xarrtools").resolve()
    assert result == expected
    assert result.is_dir()


def test_user_data_dir_windows_fallback(tmp_path, monkeypatch):
    """Windows falls back to ~\\AppData\\Roaming\\xarrtools when APPDATA is unset."""
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _get_user_data_dir("win32")
    expected = (tmp_path / "AppData" / "Roaming" / "xarrtools").resolve()
    assert result == expected
    assert result.is_dir()


def test_user_data_dir_linux_xdg(tmp_path, monkeypatch):
    """Linux resolves to $XDG_DATA_HOME/xarrtools when set."""
    fake_xdg = tmp_path / "custom_xdg_data"
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_xdg))

    result = _get_user_data_dir("linux")
    expected = (fake_xdg / "xarrtools").resolve()
    assert result == expected
    assert result.is_dir()
    if os.name == "posix":
        assert (result.stat().st_mode & 0o777) == 0o700


def test_user_data_dir_linux_fallback(tmp_path, monkeypatch):
    """Linux falls back to ~/.local/share/xarrtools when XDG_DATA_HOME is unset."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _get_user_data_dir("linux")
    expected = (tmp_path.resolve() / ".local" / "share" / "xarrtools").resolve()
    assert result == expected
    assert result.is_dir()
    if os.name == "posix":
        assert (result.stat().st_mode & 0o777) == 0o700


def test_wheel_site_packages_fallback_end_to_end(tmp_path, monkeypatch):
    """End-to-end test of get_data_dir() when running as wheel/site-packages on any OS."""
    fake_home = tmp_path / "user_home"
    fake_home.mkdir()

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("XARRTOOLS_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # Mock _detect_source_checkout to simulate non-editable wheel install in site-packages
    with patch("xarrtools.core.paths._detect_source_checkout", return_value=None):
        # 1. Test Darwin fallback
        with patch.object(sys, "platform", "darwin"):
            darwin_dir = get_data_dir()
            assert darwin_dir == (fake_home.resolve() / "Library" / "Application Support" / "xarrtools").resolve()
            assert darwin_dir.is_dir()

        # 2. Test Win32 fallback
        with patch.object(sys, "platform", "win32"):
            win_dir = get_data_dir()
            assert win_dir == (fake_home / "AppData" / "Roaming" / "xarrtools").resolve()
            assert win_dir.is_dir()

        # 3. Test Linux fallback
        with patch.object(sys, "platform", "linux"):
            linux_dir = get_data_dir()
            assert linux_dir == (fake_home.resolve() / ".local" / "share" / "xarrtools").resolve()
            assert linux_dir.is_dir()


def test_get_data_dir_idempotent(tmp_path, monkeypatch):
    """Calling get_data_dir repeatedly returns identical resolved path without error."""
    fake_home = tmp_path / "home"
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("XARRTOOLS_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    with patch("xarrtools.core.paths._detect_source_checkout", return_value=None):
        with patch.object(sys, "platform", "linux"):
            p1 = get_data_dir()
            p2 = get_data_dir()
            assert p1 == p2
            assert p1.is_dir()
