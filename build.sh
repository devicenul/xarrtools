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

echo ""
echo "Compiling xarrtools to a single executable..."
.venv/bin/pyinstaller --onefile --name xarrtools --add-data "web/templates:web/templates" main.py

if [ $? -eq 0 ]; then
    echo ""
    echo "[Success] Compilation complete!"
    echo "Binary available at: dist/xarrtools"
else
    echo ""
    echo "[Error] Compilation failed."
    exit 1
fi
