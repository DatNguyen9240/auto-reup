import time
from playwright.sync_api import sync_playwright

def generate_douyin_cookies():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        print("Đang truy cập Douyin để tự động lấy cookies...")
        page.goto('https://www.douyin.com/', wait_until='domcontentloaded')
        
        # Wait a bit for Douyin's scripts to generate the __ac_signature
        time.sleep(3)
        
        cookies = context.cookies()
        
        has_signature = any(c['name'] == '__ac_signature' for c in cookies)
        if not has_signature:
            print("Đang đợi thêm để Douyin xác thực JS...")
            page.evaluate("window.scrollBy(0, 500)")
            time.sleep(3)
            cookies = context.cookies()
            
        browser.close()
        
        # Convert to Netscape format
        with open('cookies.txt', 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies:
                domain = c['domain']
                if not domain.startswith('.'):
                    domain = '.' + domain
                secure = "TRUE" if c.get('secure') else "FALSE"
                expires = str(int(c.get('expires', 0))) if c.get('expires', -1) > 0 else "0"
                f.write(f"{domain}\tTRUE\t{c['path']}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")
                
        print(f"Đã lưu {len(cookies)} cookies vào cookies.txt!")
        return True

if __name__ == "__main__":
    generate_douyin_cookies()
