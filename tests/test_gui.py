"""Tests for pywebview desktop GUI launcher and DesktopApi bridge."""
import sys
import socket
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from gui.gui import (
    DesktopApi,
    get_free_port,
    wait_for_server,
    get_icon_path,
    hide_console,
    ensure_gui_available
)


def test_desktop_api_no_window():
    """Returns an error if pywebview has no active or open window."""
    api = DesktopApi(port=5000)
    with patch("webview.active_window", return_value=None), patch("webview.windows", []):
        res = api.save_file("/api/backup/export", "test.json")
        assert res["status"] == "error"
        assert "No active window" in res["message"]


def test_desktop_api_dialog_cancelled():
    """Returns cancelled status if user dismisses or cancels the save dialog."""
    api = DesktopApi(port=5000)
    mock_window = MagicMock()
    mock_window.create_file_dialog.return_value = None

    with patch("webview.active_window", return_value=mock_window):
        res = api.save_file("/api/backup/export", "test.json")
        assert res["status"] == "cancelled"

    # Also test empty tuple / list
    mock_window.create_file_dialog.return_value = ()
    with patch("webview.active_window", return_value=mock_window):
        res = api.save_file("/api/backup/export", "test.json")
        assert res["status"] == "cancelled"


def test_desktop_api_file_type_filters():
    """Verifies that file types filter adapts to .json, .zip, and generic extensions."""
    import webview
    save_dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", 30))
    api = DesktopApi(port=5000)
    mock_window = MagicMock()
    mock_window.create_file_dialog.return_value = None

    with patch("webview.active_window", return_value=mock_window):
        api.save_file("/api/backup/export", "backup.json")
        mock_window.create_file_dialog.assert_called_with(
            save_dialog_type,
            save_filename="backup.json",
            file_types=("JSON Files (*.json)", "All Files (*.*)")
        )

        api.save_file("/api/logs/download", "logs.zip")
        mock_window.create_file_dialog.assert_called_with(
            save_dialog_type,
            save_filename="logs.zip",
            file_types=("ZIP Archives (*.zip)", "All Files (*.*)")
        )

        api.save_file("/api/export", "other.txt")
        mock_window.create_file_dialog.assert_called_with(
            save_dialog_type,
            save_filename="other.txt",
            file_types=("All Files (*.*)",)
        )


def test_desktop_api_save_success_and_alias():
    """Streams data from local server and saves to chosen destination path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_path = Path(tmpdir) / "output.json"
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = (str(dest_path),)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b'{"status": ', b'"ok"}']
        mock_resp.__enter__.return_value = mock_resp

        api = DesktopApi(port=5432)
        with patch("webview.active_window", return_value=mock_window), \
             patch("requests.get", return_value=mock_resp) as mock_get:

            res = api.save_file("/api/backup/export?format=json", "output.json")
            assert res["status"] == "success"
            assert res["path"] == str(dest_path)
            assert dest_path.read_text(encoding="utf-8") == '{"status": "ok"}'
            mock_get.assert_called_with(
                "http://127.0.0.1:5432/api/backup/export?format=json",
                stream=True,
                timeout=120
            )

            # Test camelCase alias saveFile
            dest_path_alias = Path(tmpdir) / "alias.json"
            mock_window.create_file_dialog.return_value = str(dest_path_alias)
            mock_resp.iter_content.return_value = [b'{"alias": true}']
            res_alias = api.saveFile("/api/backup/export?format=json", "alias.json")
            assert res_alias["status"] == "success"
            assert dest_path_alias.read_text(encoding="utf-8") == '{"alias": true}'


def test_desktop_api_request_failure():
    """Handles network request or I/O failure gracefully with error status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_path = Path(tmpdir) / "error.json"
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = [str(dest_path)]

        api = DesktopApi(port=5000)
        with patch("webview.active_window", return_value=mock_window), \
             patch("requests.get", side_effect=RuntimeError("Connection refused")):
            res = api.save_file("/api/backup/export", "error.json")
            assert res["status"] == "error"
            assert "Connection refused" in res["message"]


def test_get_free_port():
    """Returns a valid bindable port number."""
    port = get_free_port()
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_wait_for_server():
    """Tests wait_for_server against a bound socket and an unused socket."""
    # Free port that is not listening
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert wait_for_server(port, timeout=0.1) is False

    # Bound listening socket
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listen_port = listener.getsockname()[1]
    try:
        assert wait_for_server(listen_port, timeout=0.5) is True
    finally:
        listener.close()


def test_get_icon_path():
    """Resolves icon path without error."""
    icon = get_icon_path()
    if icon is not None:
        assert Path(icon).exists()


def test_hide_console_windows():
    """Calls ShowWindow on Windows or skips cleanly elsewhere."""
    if sys.platform == "win32":
        with patch("ctypes.windll.kernel32.GetConsoleWindow", return_value=123), \
             patch("ctypes.windll.user32.ShowWindow") as mock_show:
            hide_console()
            mock_show.assert_called_with(123, 0)
    else:
        hide_console()


def test_ensure_gui_available_no_display():
    """Raises RuntimeError on Linux when DISPLAY is missing."""
    with patch("sys.platform", "linux"), patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="No graphical display"):
            ensure_gui_available()
