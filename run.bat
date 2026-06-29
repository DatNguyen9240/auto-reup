@echo off
title AutoTool Studio Launcher
echo =======================================================
echo   AUTOTOOL STUDIO - ALL-IN-ONE LAUNCHER
echo =======================================================
echo.

rem 1. Install dependencies
echo [1/3] Checking and installing Python dependencies...
call venv\Scripts\pip.exe install -r app/requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install Python packages.
    pause
    exit /b %ERRORLEVEL%
)

rem 2. Execute cleanup script
echo [2/3] Running project cleanup and reorganization...
if exist cleanup.bat (
    call cleanup.bat nopause
)

rem 3. Open browser and start server
echo [3/3] Starting API Server on port 8088...
echo.
echo Opening browser at http://127.0.0.1:8088 ...
start http://127.0.0.1:8088
echo.
echo Server is starting up. To close the server, press Ctrl + C in this window.
echo.

venv\Scripts\python.exe app/main.py server --port 8088
pause

