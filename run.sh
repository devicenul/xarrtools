#!/bin/bash

echo "=================================================="
echo "  xarrtools Unix Auto-Startup Launcher"
echo "=================================================="

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "[Error] Python 3 is not installed or not in your PATH."
        echo "Please install Python 3 and try again."
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# 2. Setup virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment (.venv)..."
    $PYTHON_CMD -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[Error] Failed to create virtual environment."
        exit 1
    fi
fi

# 3. Install/Update requirements
echo "Checking and installing dependencies..."
.venv/bin/pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[Error] Failed to install requirements."
    exit 1
fi

# 4. Check for .env config
if [ ! -f ".env" ]; then
    echo "Config file .env not found. Creating from template..."
    cp .env.example .env
    echo ""
    echo "Created .env config. Please edit it with your Radarr and Sonarr details."
    echo "Edit the .env file, then run this script again!"
    exit 0
fi

# 5. Run the application
echo ""
echo "Booting xarrtools..."
echo "--------------------------------------------------"
.venv/bin/python main.py
echo "--------------------------------------------------"
echo "Application closed."
