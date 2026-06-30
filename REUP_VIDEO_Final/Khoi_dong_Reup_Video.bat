@echo off
chcp 65001 >nul
echo =========================================
echo    ĐANG KHỞI ĐỘNG HỆ THỐNG REUP VIDEO
echo =========================================
echo.
echo Đang mở trình duyệt...
start http://localhost:8000

echo Đang khởi chạy Server... Hãy giữ nguyên cửa sổ màu đen này trong lúc sử dụng nhé!
echo.
cd /d "c:\Python\REUP VIDEO"
python server.py
pause
