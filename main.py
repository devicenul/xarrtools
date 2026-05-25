import sys
import webbrowser
from threading import Timer
from xarrtools.cli import run_cli
from xarrtools.server import start_server

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
        # Schedule the browser open in 1.5 seconds to allow Flask to bind to the port
        Timer(1.5, open_browser).start()
        start_server(port=5000)
