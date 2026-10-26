"""Main entry point for xarrtools (desktop GUI, web server, and CLI modes)."""
import sys
import webbrowser
import argparse
import logging
from threading import Timer
from typing import Optional
from cli import run_cli
from web import start_server

logger = logging.getLogger("xarrtools.main")


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something is already listening on host:port (e.g. a stale xarrtools instance)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) == 0


def run_server_mode(debug: bool = False, port: int = 5000) -> None:
    """Starts the web server and opens a browser, unless the port is already taken."""
    if port_in_use(port):
        logger.error(f"Port {port} is already in use.")
        print(f"[Error] Port {port} is already in use - another xarrtools instance may still be running.\n"
              f"        Find it with:  ss -ltnp | grep :{port}   (or: lsof -i :{port})\n"
              f"        then stop it, or open http://localhost:{port} if that is the instance you want.",
              file=sys.stderr)
        sys.exit(1)
    # Schedule browser opening shortly after server initialization
    Timer(1.5, open_browser).start()
    start_server(port=port, debug=debug)


def open_browser() -> None:
    """Timer callback to automatically open the default web browser."""
    logger.info("Opening browser to http://localhost:5000...")
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    # Set up argument parsing with mutually exclusive operational modes
    parser = argparse.ArgumentParser(description="xarrtools - Radarr & Sonarr Media Discovery Companion")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gui", "-g", action="store_true", help="Launch the standalone desktop GUI (default)")
    group.add_argument("--server", "-s", action="store_true", help="Start the standard Flask web server and open a browser")
    group.add_argument("--cli", "-c", action="store_true", help="Start the interactive command-line terminal manager")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debugging mode")
    
    # Use parse_known_args to ignore PyInstaller/system flags safely
    args, unknown = parser.parse_known_args()

    from core.logging_setup import setup_logging
    setup_logging(level="DEBUG" if args.debug else None)

    # Dispatch to requested operational mode
    if args.cli:
        run_cli()
    elif args.server:
        run_server_mode(debug=args.debug)
    else:
        # Standalone desktop app mode with server-fallback if graphical components are missing
        try:
            from gui.gui import run_gui
            run_gui(debug=args.debug)
        except Exception as e:
            if args.gui:
                logger.warning(f"Standalone GUI window failed to initialize: {e}")
                print(f"[Warning] Standalone GUI window failed to initialize: {e}", file=sys.stderr)
                print("Falling back to standard browser-based server mode...", file=sys.stderr)
            else:
                logger.info("Launching in standard browser-based server mode...")
                print("Launching in standard browser-based server mode...")
            run_server_mode(debug=args.debug)


