import sys
import webbrowser
import argparse
from threading import Timer
from cli import run_cli
from web import start_server

def open_browser():
    """Timer callback to automatically open the default web browser."""
    print("Opening browser to http://localhost:5000...")
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    # Set up argument parsing with safe fallback handling
    parser = argparse.ArgumentParser(description="xarrtools - Radarr & Sonarr Media Discovery Companion")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gui", "-g", action="store_true", help="Launch the standalone desktop GUI (default)")
    group.add_argument("--server", "-s", action="store_true", help="Start the standard Flask web server and open a browser")
    group.add_argument("--cli", "-c", action="store_true", help="Start the interactive command-line terminal manager")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debugging mode")
    
    # Use parse_known_args to ignore PyInstaller/system flags safely
    args, unknown = parser.parse_known_args()

    if args.cli:
        run_cli()
    elif args.server:
        Timer(1.5, open_browser).start()
        start_server(port=5000, debug=args.debug)
    else:
        # Standalone desktop app mode with server-fallback if graphical components are missing
        try:
            from gui.gui import run_gui
            run_gui(debug=args.debug)
        except Exception as e:
            if args.gui:
                print(f"[Warning] Standalone GUI window failed to initialize: {e}", file=sys.stderr)
                print("Falling back to standard browser-based server mode...", file=sys.stderr)
            else:
                print("Launching in standard browser-based server mode...")
            Timer(1.5, open_browser).start()
            start_server(port=5000, debug=args.debug)

