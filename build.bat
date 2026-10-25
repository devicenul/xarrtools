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

:: 2. Compile (icon/data-path/workpath selection and PyInstaller install live in build.py)
echo.
"%VENV_DIR%\Scripts\python.exe" build.py
set "BUILD_EXIT=%ERRORLEVEL%"

if not defined CI pause
popd
exit /b %BUILD_EXIT%
