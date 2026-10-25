"""Tests for the cross-platform build script (build.py) and the dev requirements it relies on."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("xarrtools_build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_platform_settings():
    win = build.build_settings("win32")
    assert win["separator"] == ";" and win["icon"].endswith("favicon.ico") and win["binary"].name == "xarrtools.exe"
    mac = build.build_settings("darwin")
    assert mac["separator"] == ":" and mac["icon"].endswith("favicon.icns") and mac["binary"].name == "xarrtools"
    lin = build.build_settings("linux")
    assert lin["separator"] == ":" and lin["icon"].endswith("favicon.png")


def test_icons_exist_for_every_platform():
    for platform in ("win32", "darwin", "linux"):
        assert (ROOT / build.build_settings(platform)["icon"]).is_file()


def test_pyinstaller_args_and_workpath():
    args = build.pyinstaller_args(build.build_settings("linux", cache_dir="/cache/x"))
    assert args[0] == "--onefile" and args[-1] == "main.py"
    assert "web/templates:web/templates" in args
    assert args[args.index("--workpath") + 1] == str(Path("/cache/x") / "pyinstaller-build")
    assert "--workpath" not in build.pyinstaller_args(build.build_settings("linux"))
    assert "web/templates;web/templates" in build.pyinstaller_args(build.build_settings("win32"))


def test_main_success_and_failure(capsys):
    with patch.object(build, "ensure_pyinstaller"), patch.object(build.subprocess, "call", return_value=0) as call, \
         patch.object(build.os, "chdir"), patch.dict(build.os.environ, {}, clear=False):
        assert build.main() == 0
    assert call.call_args.args[0][1:3] == ["-m", "PyInstaller"]
    assert "Compilation complete" in capsys.readouterr().out
    with patch.object(build, "ensure_pyinstaller"), patch.object(build.subprocess, "call", return_value=1), \
         patch.object(build.os, "chdir"):
        assert build.main() == 1
    assert "Compilation failed" in capsys.readouterr().err


def test_ensure_pyinstaller_installs_only_when_missing():
    with patch.object(build.importlib.util, "find_spec", return_value=object()), \
         patch.object(build.subprocess, "check_call") as pip:
        build.ensure_pyinstaller()
    pip.assert_not_called()
    with patch.object(build.importlib.util, "find_spec", return_value=None), \
         patch.object(build.subprocess, "check_call") as pip:
        build.ensure_pyinstaller()
    assert "requirements-dev.txt" in pip.call_args.args[0][-1]


def test_dev_requirements_and_init_scripts_use_them():
    dev = (ROOT / "requirements-dev.txt").read_text()
    for needed in ("-r requirements.txt", "pytest", "pytest-cov", "pyinstaller"):
        assert needed in dev
    for script in ("init.sh", "init.ps1", "init.bat"):
        assert "requirements-dev.txt" in (ROOT / script).read_text(), script
    for script in ("build.sh", "build.ps1", "build.bat"):
        text = (ROOT / script).read_text()
        assert "build.py" in text and "pip install pyinstaller" not in text.lower(), script
