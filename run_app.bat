@echo off
title VENTURE Desktop Launcher
echo Launching VENTURE Assistant...
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    call venv\Scripts\activate.bat
    python gui_app.py
) else (
    python gui_app.py
)
pause
