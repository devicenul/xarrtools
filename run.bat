@echo off
setlocal

echo ==================================================
echo   xarrtools Auto-Startup Launcher
echo ==================================================

:: 1. Check for Python
where python >nul 2>nul
if not errorlevel 1 goto check_venv
echo [Error] Python is not installed or not in your PATH.
echo Please install Python and try again.
pause
exit /b 1

:check_venv
:: 2. Setup virtual environment if missing
if exist .venv goto install_deps
echo Creating virtual environment (.venv)...
python -m venv .venv
if not errorlevel 1 goto install_deps
echo [Error] Failed to create virtual environment.
pause
exit /b 1

:install_deps
:: 3. Install/Update requirements
echo Checking and installing dependencies...
.venv\Scripts\pip install -r requirements.txt
if not errorlevel 1 goto check_env
echo [Error] Failed to install requirements.
pause
exit /b 1

:check_env
:: 4. Check for .env config
if exist .env goto run_app
echo Config file .env not found. Creating from template...
copy .env.example .env >nul
echo.
echo Created .env config. Please edit it with your Radarr and Sonarr details.
echo Press any key to open the .env file in Notepad...
pause
start notepad .env
echo.
echo Please edit the file in Notepad, save, close it, and run this launcher again!
pause
exit /b 0

:run_app
:: 5. Run the application
echo.
echo Booting xarrtools...
echo --------------------------------------------------
.venv\Scripts\python main.py
echo --------------------------------------------------
echo Application closed.
pause
