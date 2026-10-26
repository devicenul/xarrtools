"""Startup behaviour of main.py: a busy port must give a clear error and must not open a browser."""
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402


def _listening_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


def test_port_in_use_detects_listener_and_free_port():
    s, port = _listening_socket()
    try:
        assert main.port_in_use(port) is True
    finally:
        s.close()
    assert main.port_in_use(port) is False


def test_run_server_mode_exits_cleanly_when_port_busy(capsys):
    s, port = _listening_socket()
    try:
        with patch.object(main, "start_server") as start, patch.object(main, "Timer") as timer:
            with pytest.raises(SystemExit) as exc:
                main.run_server_mode(port=port)
    finally:
        s.close()
    assert exc.value.code == 1
    start.assert_not_called()
    timer.assert_not_called()   # no browser opened to someone else's server
    err = capsys.readouterr().err
    assert f"Port {port} is already in use" in err and "ss -ltnp" in err


def test_run_server_mode_starts_server_and_browser_when_free():
    with patch.object(main, "port_in_use", return_value=False), \
         patch.object(main, "start_server") as start, patch.object(main, "Timer") as timer:
        main.run_server_mode(debug=True, port=5999)
    timer.assert_called_once()
    start.assert_called_once_with(port=5999, debug=True)
