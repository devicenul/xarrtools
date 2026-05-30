import sys
import webbrowser
from threading import Timer
from cli import run_cli
from web import start_server

def open_browser():
    """Timer callback to automatically open the default web browser."""
    print("Opening browser to http://localhost:5000...")
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    # If '--cli' is passed as an argument, launch the console version.
    # Otherwise, default to starting the web interface server.
    if "--cli" in sys.argv:
        run_cli()
    else:
        debug_mode = "--debug" in sys.argv or "-d" in sys.argv
        # Schedule the browser open in 1.5 seconds to allow Flask to bind to the port
        Timer(1.5, open_browser).start()
        start_server(port=5000, debug=debug_mode)
