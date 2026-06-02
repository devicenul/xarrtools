@echo off
setlocal

echo ==================================================
echo   xarrtools Compiler Script (Windows)
echo ==================================================

:: Check if PyInstaller is installed in venv, install if missing
if not exist .venv (
    echo [Error] Virtual environment not found. Run run.bat first!
    pause
    exit /b 1
)

echo Ensuring PyInstaller is installed in the virtual environment...
.venv\Scripts\pip install pyinstaller

echo.
echo Compiling xarrtools to a single executable...
.venv\Scripts\pyinstaller --onefile --name xarrtools --icon=web/templates/favicon.ico --add-data "web/templates;web/templates" main.py

if not errorlevel 1 (
    echo.
    echo [Success] Compilation complete!
    echo Binary available at: dist\xarrtools.exe
) else (
    echo.
    echo [Error] Compilation failed.
)

pause
