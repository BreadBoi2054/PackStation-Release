@echo off
echo ==========================================
echo  PackStation - Portable Launcher
echo ==========================================
echo.

cd /d "%~dp0"

REM Check if running from dist (portable build)
if exist "PackStation.exe" (
    start "" "PackStation.exe"
    exit /b
)

REM Dev mode - run with Python
python main.py
if errorlevel 1 (
    echo.
    echo ERROR: Failed to start. Make sure Python is installed.
    echo Run: pip install -r requirements.txt
    pause
)
