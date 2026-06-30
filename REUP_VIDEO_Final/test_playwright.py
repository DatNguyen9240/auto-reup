from playwright.sync_api import sync_playwright
import urllib.request
import re

def get_douyin_info(url):
    if 'v.douyin.com' in url:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.url
        except Exception:
            pass

    video_info = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def handle_response(response):
            nonlocal video_info
            if 'aweme/detail/' in response.url or 'aweme/iteminfo/' in response.url:
                try:
                    data = response.json()
                    aweme = data.get('aweme_detail')
                    if aweme:
                        video_info = {
                            "title": aweme.get('desc'),
                            "duration": aweme.get('video', {}).get('duration', 0) // 1000,
                            "thumbnail": aweme.get('video', {}).get('cover', {}).get('url_list', [''])[0],
                            "play_addr": aweme.get('video', {}).get('play_addr', {}).get('url_list', [''])[0]
                        }
                        print("FOUND INFO!")
                except Exception:
                    pass

        page.on("response", handle_response)
        
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(8000) # wait 8 seconds for API response
        except Exception as e:
            print("Timeout, but checking if we got info...")
            
        browser.close()

    return video_info

if __name__ == "__main__":
    print(get_douyin_info('https://v.douyin.com/xJK9LqMZZNc/'))
