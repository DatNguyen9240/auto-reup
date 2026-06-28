import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.downloader import auto_generate_douyin_cookies

if __name__ == "__main__":
    print("=" * 50)
    print("  TỰ ĐỘNG TẠO COOKIES DOUYIN (PLAYWRIGHT)")
    print("=" * 50)
    print()
    
    cookie_file = project_root / "cookies.txt"
    success = auto_generate_douyin_cookies(cookie_file)
    
    if success:
        print(f"\n✅ Tự động tạo cookies thành công!")
        print(f"📁 Thư mục lưu: {cookie_file}")
    else:
        print("\n❌ Không tạo được cookies tự động.")
