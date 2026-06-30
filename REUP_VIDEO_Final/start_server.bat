@echo off
title Reup Video Douyin - Server
echo.
echo ==========================================
echo   REUP VIDEO DOUYIN - Server
echo ==========================================
echo.
echo Dang khoi dong server...
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python! Hay cai dat Python truoc.
    pause
    exit /b 1
)

:: Check if dependencies installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Dang cai dat dependencies lan dau...
    pip install -r requirements.txt
    echo.
)

:: Start server
echo [OK] Server dang chay tai: http://localhost:8000
echo [OK] Mo tren dien thoai: Dung Cloudflare Tunnel hoac ngrok
echo.
echo Nhan Ctrl+C de dung server.
echo.

python server.py
pause
