@echo off
setlocal
title AutoTool Studio Launcher
cd /d "%~dp0"

echo =======================================================
echo   AUTOTOOL STUDIO - ALL-IN-ONE LAUNCHER
echo =======================================================
echo.

rem 1. Install dependencies
echo [INFO] Ensuring Port 8088 is free...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8088 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo [INFO] Stopping old AutoTool server processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = (Resolve-Path '.').Path; Get-CimInstance Win32_Process -Filter \"name = 'python.exe' or name = 'pythonw.exe'\" | Where-Object { ($_.CommandLine -like ('*' + $root + '*')) -or ($_.CommandLine -like '*app\main.py*server*') -or ($_.CommandLine -like '*app/main.py*server*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [1/3] Checking and installing Python dependencies...
if not exist "app\requirements.txt" (
    echo [ERROR] Missing app\requirements.txt. Please run this launcher from the project folder.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [INFO] Creating Python virtual environment...
    py -3.11 -m venv venv
    if errorlevel 1 (
        py -3.12 -m venv venv
    )
    if errorlevel 1 (
        py -3.10 -m venv venv
    )
    if errorlevel 1 (
        py -3 -m venv venv
    )
    if errorlevel 1 (
        python -m venv venv
    )
    if not exist "venv\Scripts\python.exe" (
        echo [ERROR] Failed to create virtual environment. Please install Python 3 and enable the py launcher or python command.
        pause
        exit /b 1
    )
)

call "venv\Scripts\python.exe" -m pip install --upgrade pip
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b %ERRORLEVEL%
)

call "venv\Scripts\python.exe" -m pip install -r "app\requirements.txt"
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

call "venv\Scripts\python.exe" "app\main.py" server --port 8088 --reload
pause

