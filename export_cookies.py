import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.downloader import export_cookies_from_browser

if __name__ == "__main__":
    print("=" * 50)
    print("  XUẤT COOKIES DOUYIN TỪ TRÌNH DUYỆT")
    print("=" * 50)
    print()
    
    cookie_file = project_root / "cookies.txt"
    success = export_cookies_from_browser(cookie_file)
    
    if success:
        print(f"\n✅ Xuất cookies thành công!")
        print(f"📁 Thư mục lưu: {cookie_file}")
    else:
        print("\n❌ Không xuất được cookies từ bất kỳ trình duyệt nào.")
        print("Vui lòng đảm bảo bạn đã đóng hoàn toàn Chrome/Edge trước khi chạy.")
