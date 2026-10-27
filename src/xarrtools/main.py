"""Main entry point for xarrtools (desktop GUI, web server, and CLI modes)."""
import os
import sys
import webbrowser
import argparse
import logging
from threading import Timer
from typing import Optional
from xarrtools.cli import run_cli
from xarrtools.web import start_server

logger = logging.getLogger("xarrtools.main")


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something is already listening on host:port (e.g. a stale xarrtools instance)."""
    import socket
    check_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((check_host, port)) == 0


def run_server_mode(
    debug: bool = False,
    port: int = 5000,
    host: Optional[str] = None,
    no_browser: bool = False,
) -> None:
    """Starts the web server and opens a browser, unless the port is already taken."""
    effective_host = host if host is not None else os.environ.get("XARRTOOLS_HOST", "127.0.0.1")
    check_host = "127.0.0.1" if effective_host in ("0.0.0.0", "", "::") else effective_host
    if port_in_use(port, host=check_host):
        logger.error(f"Port {port} is already in use.")
        print(f"[Error] Port {port} is already in use - another xarrtools instance may still be running.\n"
              f"        Find it with:  ss -ltnp | grep :{port}   (or: lsof -i :{port})\n"
              f"        then stop it, or open http://localhost:{port} if that is the instance you want.",
              file=sys.stderr)
        sys.exit(1)
    # Schedule browser opening shortly after server initialization
    if not no_browser:
        browser_host = "localhost" if effective_host in ("0.0.0.0", "127.0.0.1") else effective_host
        Timer(1.5, lambda: open_browser(port=port, host=browser_host)).start()
    if host is not None:
        start_server(port=port, debug=debug, host=host)
    else:
        start_server(port=port, debug=debug)


def open_browser(port: int = 5000, host: str = "localhost") -> None:
    """Timer callback to automatically open the default web browser."""
    target_url = f"http://{host}:{port}"
    logger.info(f"Opening browser to {target_url}...")
    webbrowser.open(target_url)


def main(argv: Optional[list] = None) -> int:
    """Main execution function parsing CLI arguments and dispatching to GUI/server/CLI."""
    parser = argparse.ArgumentParser(description="xarrtools - Radarr & Sonarr Media Discovery Companion")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gui", "-g", action="store_true", help="Launch the standalone desktop GUI (default)")
    group.add_argument("--server", "-s", action="store_true", help="Start the standard Flask web server and open a browser")
    group.add_argument("--cli", "-c", action="store_true", help="Start the interactive command-line terminal manager")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debugging mode")
    parser.add_argument("--host", default=None, help="Host/interface to bind the web server to (default: 127.0.0.1 or XARRTOOLS_HOST)")
    parser.add_argument("--port", "-p", type=int, default=None, help="Port to bind the web server to (default: 5000 or XARRTOOLS_PORT)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the web browser on startup")

    # Use parse_known_args to ignore PyInstaller/system flags safely
    args, unknown = parser.parse_known_args(argv)

    from xarrtools.core.logging_setup import setup_logging
    setup_logging(level="DEBUG" if args.debug else None)

    # Resolve port and host with environment variable fallbacks
    port = args.port
    if port is None:
        env_port = os.environ.get("XARRTOOLS_PORT")
        if env_port and env_port.isdigit():
            port = int(env_port)
        else:
            port = 5000
    host = args.host if args.host is not None else os.environ.get("XARRTOOLS_HOST")

    # Dispatch to requested operational mode
    if args.cli:
        run_cli()
    elif args.server:
        run_server_mode(debug=args.debug, port=port, host=host, no_browser=args.no_browser)
    else:
        # Standalone desktop app mode with server-fallback if graphical components are missing
        try:
            from xarrtools.gui.gui import run_gui
            run_gui(debug=args.debug)
        except Exception as e:
            if args.gui:
                logger.warning(f"Standalone GUI window failed to initialize: {e}")
                print(f"[Warning] Standalone GUI window failed to initialize: {e}", file=sys.stderr)
                print("Falling back to standard browser-based server mode...", file=sys.stderr)
            else:
                logger.info("Launching in standard browser-based server mode...")
                print("Launching in standard browser-based server mode...")
            run_server_mode(debug=args.debug, port=port, host=host, no_browser=args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())


