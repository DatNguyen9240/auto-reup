"""
Xuất cookies Douyin từ trình duyệt → cookies.txt
Chạy 1 lần khi cần. Đóng Chrome/Edge trước khi chạy.

Cách dùng:
1. Đóng Chrome (hoặc Edge)
2. Chạy: python export_cookies.py
3. Mở lại Chrome bình thường
4. File cookies.txt sẽ được tạo, tool sẽ tự dùng
"""

import subprocess
import sys
import os

BROWSERS = ["chrome", "edge", "firefox", "brave", "opera"]
OUTPUT = os.path.join(os.path.dirname(__file__), "cookies.txt")

def export():
    for browser in BROWSERS:
        print(f"Đang thử xuất cookies từ {browser}...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp",
                 "--cookies-from-browser", browser,
                 "--cookies", OUTPUT,
                 "--skip-download",
                 "https://www.douyin.com/video/7644860524542315776"],
                capture_output=True, text=True, timeout=30
            )
            if os.path.exists(OUTPUT) and os.path.getsize(OUTPUT) > 100:
                print(f"\n✅ Xuất cookies thành công từ {browser}!")
                print(f"📁 File: {OUTPUT}")
                print(f"📦 Kích thước: {os.path.getsize(OUTPUT)} bytes")
                print(f"\nBạn có thể mở lại {browser} và dùng tool bình thường.")
                return True
        except Exception as e:
            print(f"  ❌ {browser}: {e}")
    
    print("\n❌ Không xuất được cookies từ trình duyệt nào.")
    print("Hãy đảm bảo đã đóng Chrome/Edge trước khi chạy script này.")
    return False

if __name__ == "__main__":
    print("=" * 50)
    print("  XUẤT COOKIES DOUYIN")
    print("=" * 50)
    print()
    export()
