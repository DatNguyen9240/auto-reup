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

set "PYTHON_CMD="

rem Check if py launcher is available
py -0 >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PYTHON_CMD=py"
) else (
    rem Check if python is available in PATH
    python --version >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "PYTHON_CMD=python"
    ) else (
        rem Search local AppData
        if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
            set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python310\python.exe"
        )
        if not defined PYTHON_CMD (
            if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" (
                set "PYTHON_CMD=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
            )
        )
        if not defined PYTHON_CMD (
            if exist "C:\Users\Dell3070\AppData\Local\Programs\Python\Python310\python.exe" (
                set "PYTHON_CMD=C:\Users\Dell3070\AppData\Local\Programs\Python\Python310\python.exe"
            )
        )
        if not defined PYTHON_CMD (
            for /d %%d in ("%LocalAppData%\Programs\Python\Python*") do (
                if exist "%%~d\python.exe" (
                    set "PYTHON_CMD=%%~d\python.exe"
                )
            )
        )
        if not defined PYTHON_CMD (
            for /d %%d in ("%USERPROFILE%\AppData\Local\Programs\Python\Python*") do (
                if exist "%%~d\python.exe" (
                    set "PYTHON_CMD=%%~d\python.exe"
                )
            )
        )
        rem Search Program Files
        if not defined PYTHON_CMD (
            for /d %%d in ("%ProgramFiles%\Python*") do (
                if exist "%%~d\python.exe" (
                    set "PYTHON_CMD=%%~d\python.exe"
                )
            )
        )
        rem Search Program Files (x86)
        if not defined PYTHON_CMD (
            for /d %%d in ("%ProgramFiles(x86)%\Python*") do (
                if exist "%%~d\python.exe" (
                    set "PYTHON_CMD=%%~d\python.exe"
                )
            )
        )
    )
)

echo [1/3] Checking and installing Python dependencies...
if not exist "app\requirements.txt" (
    echo [ERROR] Missing app\requirements.txt. Please run this launcher from the project folder.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [INFO] Creating Python virtual environment...
    if not defined PYTHON_CMD (
        echo [ERROR] Python 3 was not found on your system.
        echo Please download and install Python from: https://www.python.org/downloads/
        echo Make sure to check the option "Add Python to PATH" during installation.
        echo.
        echo Diagnostic Info:
        echo   LocalAppData: %LocalAppData%
        echo   UserProfile:  %USERPROFILE%
        echo.
        pause
        exit /b 1
    )
    
    if "%PYTHON_CMD%"=="py" (
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
    ) else (
        "%PYTHON_CMD%" -m venv venv
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

