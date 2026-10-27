"""Pywebview desktop GUI launcher and window manager for xarrtools."""
import sys
import time
import socket
import threading
import ctypes
import logging
from pathlib import Path
from typing import Optional, Any, Dict, Union, Tuple, List, Sequence
try:
    import webview
except ImportError:
    webview = None  # type: ignore

logger = logging.getLogger("xarrtools.gui")

class DesktopApi:
    """Pywebview JavaScript API bridge for native desktop interactions (e.g. file downloads)."""

    def __init__(self, port: int) -> None:
        self.port = port

    def save_file(self, url: str, filename: str = "") -> Dict[str, Any]:
        """Prompts the user with a native Save File dialog and streams the file from the local server."""
        try:
            if webview is None:
                return {"status": "error", "message": "pywebview is not installed"}
            window = webview.active_window()
            if not window and len(webview.windows) > 0:
                window = webview.windows[0]
            if not window:
                return {"status": "error", "message": "No active window available"}

            default_name = filename or "download"
            file_types: Tuple[str, ...]
            if default_name.lower().endswith(".json"):
                file_types = ("JSON Files (*.json)", "All Files (*.*)")
            elif default_name.lower().endswith(".zip"):
                file_types = ("ZIP Archives (*.zip)", "All Files (*.*)")
            else:
                file_types = ("All Files (*.*)",)

            dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", 30))
            result = window.create_file_dialog(
                dialog_type,
                save_filename=default_name,
                file_types=file_types
            )
            if not result:
                return {"status": "cancelled"}

            file_path: Optional[str] = None
            if isinstance(result, (list, tuple)):
                if len(result) > 0 and isinstance(result[0], str):
                    file_path = result[0]
            elif isinstance(result, str):
                file_path = result

            if not file_path:
                return {"status": "cancelled"}

            download_url = url
            if download_url.startswith("/"):
                download_url = f"http://127.0.0.1:{self.port}{download_url}"

            import requests
            with requests.get(download_url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)

            logger.info(f"Successfully saved download to {file_path}")
            return {"status": "success", "path": str(file_path)}
        except Exception as e:
            logger.error(f"Failed to save file download: {e}")
            return {"status": "error", "message": str(e)}

    def saveFile(self, url: str, filename: str = "") -> Dict[str, Any]:
        """CamelCase alias for save_file."""
        return self.save_file(url, filename)

def hide_console() -> None:
    """Hides the console window when running on Windows in GUI mode."""
    # Hide the attached terminal window on Windows so GUI runs seamlessly
    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                # SW_HIDE = 0: hides the window and activates another window
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception as e:
            logger.warning(f"Failed to hide console window: {e}")
            print(f"[Warning] Failed to hide console window: {e}", file=sys.stderr)

def get_free_port() -> int:
    """Finds an available TCP port on localhost."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
        s.close()
        return port
    except Exception:
        # Fall back to default 5000 if dynamic lookup fails
        return 5000

def wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """Polls localhost at the given port to check if the Flask server has booted."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(0.1)
    return False

def get_icon_path() -> Optional[str]:
    """Resolves the absolute path to the window icon, supporting PyInstaller execution."""
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # PyInstaller runtime attribute
    else:
        base_path = Path(__file__).resolve().parent.parent
    
    if sys.platform == "win32":
        icon_path = base_path / "web" / "templates" / "favicon.ico"
        if icon_path.exists():
            return str(icon_path)
    elif sys.platform == "darwin":
        icon_path = base_path / "web" / "templates" / "favicon.icns"
        if icon_path.exists():
            return str(icon_path)
            
    icon_path = base_path / "web" / "templates" / "favicon.png"
    if icon_path.exists():
        return str(icon_path)
    return None

def ensure_gui_available() -> None:
    """Verifies that a graphical display and a supported pywebview backend exist before starting a server."""
    if webview is None:
        raise RuntimeError("pywebview is not installed; install requirements-gui.txt to use the desktop GUI.")
    import os
    import logging

    pwv_logger = logging.getLogger("pywebview")
    pwv_logger.setLevel(logging.CRITICAL)
    pwv_logger.propagate = False

    # Check for X11/Wayland display server on Linux / BSD systems
    if sys.platform.startswith("linux") or sys.platform.startswith("openbsd"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("No graphical display (DISPLAY or WAYLAND_DISPLAY) detected.")

        # Ensure either QT or GTK Python bindings are installed for pywebview rendering
        has_backend = False
        for mod_name in ("webview.platforms.gtk", "webview.platforms.qt"):
            try:
                __import__(mod_name)
                has_backend = True
                break
            except Exception:
                continue
        if not has_backend:
            raise RuntimeError(
                "You must have either QT or GTK with Python extensions installed in order to use pywebview."
            )


def run_gui(debug: bool = False) -> None:
    """Launches the Flask web server in a background daemon thread and displays the UI in a pywebview window."""
    # 0. Verify GUI display and backend availability BEFORE booting the background server
    ensure_gui_available()

    # 1. Hide the CMD console on Windows so the GUI feels standalone
    hide_console()

    # 2. Dynamically bind to a free port to prevent conflicts
    port = get_free_port()

    # 3. Import and boot standard server inside a daemon thread
    from web.server import start_server
    server_thread = threading.Thread(
        target=start_server,
        kwargs={"port": port, "debug": False},
        daemon=True
    )
    server_thread.start()

    # 4. Block briefly until Flask starts accepting connections
    if not wait_for_server(port):
        logger.error(f"Flask server failed to start on port {port} in time.")
        print(f"[Error] Flask server failed to start on port {port} in time.", file=sys.stderr)
        sys.exit(1)

    # Enable pywebview native download handling
    if hasattr(webview, "settings") and isinstance(webview.settings, dict):
        webview.settings["ALLOW_DOWNLOADS"] = True

    # 5. Create the GUI window frame pointing to the local port with native desktop js_api
    icon_path = get_icon_path()
    api = DesktopApi(port=port)
    
    # Establish a sleek default background matching xarrtools' dark aesthetic
    window = webview.create_window(
        title="xarrtools",
        url=f"http://127.0.0.1:{port}",
        js_api=api,
        width=1280,
        height=720,
        min_size=(800, 600),
        resizable=True,
        background_color="#121214"
    )

    # 6. Block the main thread and start the operating system's native WebView loop
    # Programmatic icon parameter is used for taskbar and window frames.
    if icon_path:
        webview.start(debug=debug, icon=icon_path)
    else:
        webview.start(debug=debug)

