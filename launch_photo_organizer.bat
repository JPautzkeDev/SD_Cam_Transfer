@echo off
:: ─────────────────────────────────────────────────────────────────
:: Photo Organizer Launcher
:: Place this .bat file in the same folder as photo_organizer.py
:: ─────────────────────────────────────────────────────────────────

:: Change directory to the folder this .bat file lives in
cd /d "%~dp0"

:: Launch with pythonw (no console window)
pythonw photo_organizer.py

:: If pythonw failed (e.g. Python not in PATH), show a helpful message
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Could not launch Photo Organizer.
    echo.
    echo  Please check that Python is installed and added to your PATH.
    echo  Download Python from: https://www.python.org/downloads/
    echo.
    echo  Also ensure required libraries are installed by running:
    echo    pip install pillow rawpy
    echo.
    pause
)
