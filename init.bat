@echo off
setlocal EnableDelayedExpansion

:: ==============================================================================
:: xarrtools Windows Initialization Script (init.bat)
:: ==============================================================================
:: Sets up the Python virtual environment (.venv), installs runtime and
:: test/development dependencies, creates .env from .env.example, and initializes
:: the local SQLite database schema.
:: ==============================================================================

pushd "%~dp0"

set "NO_PAUSE=0"
set "SKIP_DEPS=0"
if defined CI set "NO_PAUSE=1"

for %%A in (%*) do (
    if /I "%%~A"=="--no-pause" set "NO_PAUSE=1"
    if /I "%%~A"=="--non-interactive" set "NO_PAUSE=1"
    if /I "%%~A"=="--skip-deps" set "SKIP_DEPS=1"
)

echo ==================================================
echo   xarrtools Project Initialization (Windows)
echo ==================================================

:: 1. Locate Python 3
set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    echo [Error] Python 3 is not installed or not in your PATH.
    echo Please install Python 3 and try again.
    if "!NO_PAUSE!"=="0" pause
    popd
    exit /b 1
)

if defined XARRTOOLS_VENV_DIR (
    set "VENV_DIR=%XARRTOOLS_VENV_DIR%"
) else (
    set "VENV_DIR=.venv"
)

:: 2. Clean up broken local .venv if present
if exist "%VENV_DIR%" (
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        if not exist "%VENV_DIR%\bin\python" (
            echo [Init] Removing incomplete virtual environment directory...
            rmdir /s /q "%VENV_DIR%"
        )
    )
)

:: 3. Create virtual environment if missing
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [Init] Creating virtual environment (%VENV_DIR%)...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [Error] Failed to create virtual environment.
        if "!NO_PAUSE!"=="0" pause
        popd
        exit /b 1
    )
)

:: 4. Install runtime and test/development dependencies
if "!SKIP_DEPS!"=="0" (
    echo [Init] Installing runtime dependencies from requirements.txt...
    "%VENV_DIR%\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo [Error] Failed to install runtime requirements.
        if "!NO_PAUSE!"=="0" pause
        popd
        exit /b 1
    )

    echo [Init] Installing test and development dependencies (pytest, pytest-cov)...
    "%VENV_DIR%\Scripts\pip.exe" install pytest pytest-cov
    if errorlevel 1 (
        echo [Error] Failed to install test/development dependencies.
        if "!NO_PAUSE!"=="0" pause
        popd
        exit /b 1
    )
)

:: 5. Check for .env config
if not exist ".env" (
    if exist ".env.example" (
        echo [Init] Creating .env configuration file from .env.example...
        copy /Y ".env.example" ".env" >nul
        echo [Note] Default .env created. You can configure Radarr/Sonarr credentials in .env or via the Web UI Settings.
    ) else (
        echo [Warning] .env.example not found; skipping .env creation.
    )
) else (
    echo [Init] Existing .env configuration found.
)

:: 6. Initialize SQLite database schema
echo [Init] Initializing SQLite database schema (xarrtools.db)...
"%VENV_DIR%\Scripts\python.exe" -c "from core.db import init_db, clean_expired_cache; init_db(); clean_expired_cache()"
if errorlevel 1 (
    echo [Error] Failed to initialize SQLite database schema.
    if "!NO_PAUSE!"=="0" pause
    popd
    exit /b 1
)

echo ==================================================
echo   [Success] xarrtools initialization complete!
echo ==================================================

popd
exit /b 0
