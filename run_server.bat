@echo off
title KookAI Workspace Chat Server
cd /d "%~dp0"
echo Starting KookAI Workspace Chat Server...

if not exist "venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3 -m venv venv 2>nul
  if errorlevel 1 python -m venv venv
  if errorlevel 1 (
    echo Python 3.10+ is required but was not found.
    pause
    exit /b 1
  )
)

rem main.py installs missing Python and CLI requirements on first launch.
"venv\Scripts\python.exe" main.py
pause
