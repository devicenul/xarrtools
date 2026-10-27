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
    assert "--collect-submodules" in args
    assert "webview" in args
    assert "web/templates:web/templates" in args
    assert args[args.index("--workpath") + 1] == str(Path("/cache/x") / "pyinstaller-build")
    assert "--workpath" not in build.pyinstaller_args(build.build_settings("linux"))
    assert "web/templates;web/templates" in build.pyinstaller_args(build.build_settings("win32"))


def test_stamp_version(tmp_path):
    version_file = ROOT / "core" / "_version.py"
    try:
        ver = build.stamp_version("v1.2.3")
        assert ver == "1.2.3"
        assert version_file.is_file()
        assert '__version__ = "1.2.3"' in version_file.read_text(encoding="utf-8")
    finally:
        if version_file.exists():
            version_file.unlink()


def test_main_success_and_failure(capsys):
    with patch.object(build, "ensure_pyinstaller"), patch.object(build, "build_frontend", return_value=True), \
         patch.object(build.subprocess, "call", return_value=0) as call, \
         patch.object(build.os, "chdir"), patch.dict(build.os.environ, {}, clear=False):
        assert build.main() == 0
    assert call.call_args.args[0][1:3] == ["-m", "PyInstaller"]
    assert "Compilation complete" in capsys.readouterr().out
    with patch.object(build, "ensure_pyinstaller"), patch.object(build, "build_frontend", return_value=True), \
         patch.object(build.subprocess, "call", return_value=1), \
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
        text = (ROOT / script).read_text()
        assert "requirements-dev.txt" in text, script
        assert "package.json" in text, script
    for script in ("build.sh", "build.ps1", "build.bat"):
        text = (ROOT / script).read_text()
        assert "build.py" in text and "pip install pyinstaller" not in text.lower(), script


def test_build_frontend_skips_when_empty(tmp_path):
    assert build.build_frontend(tmp_path) is True

    src_dir = tmp_path / "web" / "static" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / ".gitkeep").write_text("")
    (src_dir / "notes.txt").write_text("notes")

    with patch.object(build.shutil, "which") as mock_which, \
         patch.object(build.subprocess, "call") as mock_call:
        assert build.build_frontend(tmp_path) is True
        mock_which.assert_not_called()
        mock_call.assert_not_called()


def test_build_frontend_npm_missing_failure(tmp_path, capsys):
    src_dir = tmp_path / "web" / "static" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "app.ts").write_text("console.log('hi');")

    with patch.object(build.shutil, "which", return_value=None):
        assert build.build_frontend(tmp_path) is False
    err = capsys.readouterr().err
    assert "Node.js (npm) is required to build the frontend" in err


def test_build_frontend_builds_when_sources_present(tmp_path):
    src_dir = tmp_path / "web" / "static" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "app.ts").write_text("console.log('hi');")

    with patch.object(build.shutil, "which", return_value="/usr/bin/npm"), \
         patch.object(build.subprocess, "call", return_value=0) as mock_call:
        assert build.build_frontend(tmp_path) is True
        assert mock_call.call_count == 2
        assert mock_call.call_args_list[0].args[0] == ["/usr/bin/npm", "install", "--no-audit", "--no-fund"]
        assert mock_call.call_args_list[1].args[0] == ["/usr/bin/npm", "run", "build"]


def test_main_call_order_frontend_before_pyinstaller():
    order = []

    def fake_build_frontend(root=None):
        order.append("frontend")
        return True

    def fake_ensure_pyinstaller():
        order.append("ensure_pyinstaller")

    def fake_call(cmd, **kwargs):
        order.append("pyinstaller")
        return 0

    with patch.object(build, "build_frontend", side_effect=fake_build_frontend), \
         patch.object(build, "ensure_pyinstaller", side_effect=fake_ensure_pyinstaller), \
         patch.object(build.subprocess, "call", side_effect=fake_call), \
         patch.object(build.os, "chdir"):
        assert build.main() == 0

    assert order == ["frontend", "ensure_pyinstaller", "pyinstaller"]


def test_main_aborts_when_frontend_fails():
    with patch.object(build, "build_frontend", return_value=False), \
         patch.object(build, "ensure_pyinstaller") as mock_ensure, \
         patch.object(build.subprocess, "call") as mock_call, \
         patch.object(build.os, "chdir"):
        assert build.main() == 1
    mock_ensure.assert_not_called()
    mock_call.assert_not_called()


def test_pyinstaller_args_conditional_dist_data():
    settings_linux = build.build_settings("linux", dist_exists=False)
    args = build.pyinstaller_args(settings_linux)
    assert not any("web/static/dist" in arg for arg in args)

    settings_linux_dist = build.build_settings("linux", dist_exists=True)
    args_dist = build.pyinstaller_args(settings_linux_dist)
    assert "web/static/dist:web/static/dist" in args_dist

    settings_win_dist = build.build_settings("win32", dist_exists=True)
    args_win = build.pyinstaller_args(settings_win_dist)
    assert "web/static/dist;web/static/dist" in args_win

    args_override = build.pyinstaller_args(settings_linux, dist_exists=True)
    assert "web/static/dist:web/static/dist" in args_override
