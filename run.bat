@echo off
setlocal EnableDelayedExpansion

:: ==============================================================================
:: xarrtools Windows Auto-Startup Launcher (run.bat)
:: ==============================================================================

pushd "%~dp0"

echo ==================================================
echo   xarrtools Auto-Startup Launcher
echo ==================================================

if defined XARRTOOLS_VENV_DIR (
    set "VENV_DIR=%XARRTOOLS_VENV_DIR%"
) else (
    set "VENV_DIR=.venv"
)

:: 1. Ensure project is initialized
set "NEEDS_FULL_INIT=0"
if not exist "%VENV_DIR%\Scripts\python.exe" set "NEEDS_FULL_INIT=1"
if not exist ".env" set "NEEDS_FULL_INIT=1"
if not exist "xarrtools.db" set "NEEDS_FULL_INIT=1"

if "!NEEDS_FULL_INIT!"=="0" (
    "%VENV_DIR%\Scripts\python.exe" -c "import flask, requests, bs4, rich, dotenv, waitress, defusedxml" >nul 2>nul
    if errorlevel 1 set "NEEDS_FULL_INIT=1"
)

if "!NEEDS_FULL_INIT!"=="1" (
    call "%~dp0init.bat" --no-pause
) else (
    call "%~dp0init.bat" --no-pause --skip-deps
)

if errorlevel 1 (
    echo [Error] Project initialization failed.
    if not defined CI pause
    popd
    exit /b 1
)

:: 2. Run the application, forwarding all CLI arguments
echo.
echo Booting xarrtools...
echo --------------------------------------------------
"%VENV_DIR%\Scripts\python.exe" main.py %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
echo --------------------------------------------------
echo Application closed.

if not defined CI pause
popd
exit /b %APP_EXIT_CODE%
