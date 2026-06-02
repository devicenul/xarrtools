#!/bin/bash

echo "=================================================="
echo "  xarrtools Compiler Script (Unix)"
echo "=================================================="

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "[Error] Virtual environment not found. Run run.sh first!"
    exit 1
fi

echo "Ensuring PyInstaller is installed in the virtual environment..."
.venv/bin/pip install pyinstaller

# Detect OS to set the appropriate icon format
OS_NAME="$(uname -s)"
if [ "$OS_NAME" = "Darwin" ]; then
    ICON_FILE="web/templates/favicon.icns"
else
    ICON_FILE="web/templates/favicon.png"
fi

echo ""
echo "Compiling xarrtools to a single executable..."
.venv/bin/pyinstaller --onefile --name xarrtools --icon="$ICON_FILE" --add-data "web/templates:web/templates" main.py

if [ $? -eq 0 ]; then
    echo ""
    echo "[Success] Compilation complete!"
    echo "Binary available at: dist/xarrtools"
else
    echo ""
    echo "[Error] Compilation failed."
    exit 1
fi
