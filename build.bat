@echo off
setlocal EnableDelayedExpansion

:: ==============================================================================
:: xarrtools Compiler Script (Windows)
:: ==============================================================================

pushd "%~dp0"

echo ==================================================
echo   xarrtools Compiler Script (Windows)
echo ==================================================

if defined XARRTOOLS_VENV_DIR (
    set "VENV_DIR=%XARRTOOLS_VENV_DIR%"
) else (
    set "VENV_DIR=.venv"
)

:: 1. Initialize virtual environment via init.bat if missing
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [Build] Virtual environment not found. Running init.bat first...
    call "%~dp0init.bat" --no-pause
    if errorlevel 1 (
        echo [Error] Failed to initialize environment via init.bat.
        if not defined CI pause
        popd
        exit /b 1
    )
)

echo Ensuring PyInstaller is installed in the virtual environment...
"%VENV_DIR%\Scripts\pip.exe" install pyinstaller
if errorlevel 1 (
    echo [Error] Failed to install PyInstaller.
    if not defined CI pause
    popd
    exit /b 1
)

echo.
echo Compiling xarrtools to a single executable...
"%VENV_DIR%\Scripts\pyinstaller.exe" --onefile --name xarrtools --icon=web/templates/favicon.ico --add-data "web/templates;web/templates" main.py

if not errorlevel 1 (
    echo.
    echo [Success] Compilation complete!
    echo Binary available at: dist\xarrtools.exe
    set "BUILD_EXIT=0"
) else (
    echo.
    echo [Error] Compilation failed.
    set "BUILD_EXIT=1"
)

if not defined CI pause
popd
exit /b %BUILD_EXIT%
