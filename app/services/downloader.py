import os
import re
import sys
import time
import logging
import asyncio
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Dict
import requests
import requests.cookies
from playwright.sync_api import sync_playwright

logger = logging.getLogger("Downloader")

def normalize_douyin_url(url: str) -> str:
    """Convert various Douyin URL formats to a standard format yt-dlp/playwright can handle."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    # Handle jingxuan/discover URLs with modal_id parameter
    # e.g. https://www.douyin.com/jingxuan?modal_id=7647094786759865807
    if "modal_id" in query:
        video_id = query["modal_id"][0]
        return f"https://www.douyin.com/video/{video_id}"

    return url


def _load_cookies_from_file(cookie_file_path: Path) -> requests.cookies.RequestsCookieJar:
    """Load cookies in Netscape format and return a RequestsCookieJar."""
    jar = requests.cookies.RequestsCookieJar()
    if not cookie_file_path.exists():
        logger.warning(f"Cookie file not found at: {cookie_file_path}")
        return jar
    try:
        with open(cookie_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    domain, flag, path, secure, expiration, name, value = parts[:7]
                    
                    try:
                        expires = int(expiration)
                    except ValueError:
                        expires = None
                        
                    jar.set(
                        name,
                        value,
                        domain=domain,
                        path=path,
                        secure=secure.upper() == "TRUE",
                        expires=expires
                    )
    except Exception as e:
        logger.error(f"Error loading cookies from file: {e}")
    return jar


_METADATA_CACHE = {}

def get_douyin_metadata_playwright(url: str, cookie_file_path: Path) -> dict:
    """Extract video metadata and direct play_addr using Playwright."""
    if url in _METADATA_CACHE:
        return _METADATA_CACHE[url]

    # Resolve short URL first
    resolved_url = url
    if 'v.douyin.com' in resolved_url:
        req = urllib.request.Request(resolved_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resolved_url = resp.url
        except Exception as e:
            logger.warning(f"Error resolving short URL: {e}")

    if resolved_url in _METADATA_CACHE:
        return _METADATA_CACHE[resolved_url]
            
    video_info = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        
        # Load and inject cookies if exists
        cookie_jar = _load_cookies_from_file(cookie_file_path)
        playwright_cookies = []
        for c in cookie_jar:
            p_cookie = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
            }
            if c.expires:
                p_cookie["expires"] = c.expires
            playwright_cookies.append(p_cookie)
            
        if playwright_cookies:
            context.add_cookies(playwright_cookies)
            logger.info(f"Loaded {len(playwright_cookies)} cookies into Playwright context")
            
        page = context.new_page()

        def handle_response(response):
            nonlocal video_info
            if 'aweme/detail/' in response.url or 'aweme/iteminfo/' in response.url:
                try:
                    data = response.json()
                    aweme = data.get('aweme_detail')
                    if aweme:
                        video_info = {
                            "title": aweme.get('desc', 'Video Douyin'),
                            "duration": aweme.get('video', {}).get('duration', 0) // 1000,
                            "thumbnail": aweme.get('video', {}).get('cover', {}).get('url_list', [''])[0],
                            "play_addr": aweme.get('video', {}).get('play_addr', {}).get('url_list', [''])[0],
                            "view_count": aweme.get('statistics', {}).get('play_count', 0),
                            "like_count": aweme.get('statistics', {}).get('digg_count', 0),
                            "uploader": aweme.get('author', {}).get('nickname', ''),
                        }
                except Exception as e:
                    logger.debug(f"JSON parsing error: {e}")

        page.on("response", handle_response)
        
        try:
            logger.info(f"Navigating browser to: {resolved_url}")
            page.goto(resolved_url, wait_until='domcontentloaded', timeout=60000)
            
            # Polling wait to allow user to solve Captcha if it appears
            for _ in range(12):  # Wait up to 60 seconds (12 * 5s)
                if video_info and video_info.get("play_addr"):
                    break
                page.wait_for_timeout(5000)
                
            if not video_info or not video_info.get("play_addr"):
                page.screenshot(path="playwright_screenshot.png")
                logger.info("Saved Playwright troubleshooting screenshot to playwright_screenshot.png")
        except Exception as e:
            logger.warning(f"Browser navigation warning: {e}")
            try:
                page.screenshot(path="playwright_screenshot.png")
            except Exception:
                pass
            
        browser.close()

    if not video_info or not video_info.get("play_addr"):
        raise Exception("Không thể lấy thông tin video từ Douyin (Bị chặn hoặc URL không hợp lệ).")
        
    _METADATA_CACHE[url] = video_info
    _METADATA_CACHE[resolved_url] = video_info
    
    return video_info


class PlaywrightDownloaderService:
    def __init__(self, cookie_file_path: Optional[Path] = None):
        if cookie_file_path is None:
            # Default to cookies.txt in the root of the project
            self.cookie_file_path = Path(__file__).resolve().parents[2] / "cookies.txt"
        else:
            self.cookie_file_path = Path(cookie_file_path)

    async def download_video_async(self, url: str, dest_path: Path) -> dict:
        """Download video asynchronously by running requests download in executor."""
        url = normalize_douyin_url(url)
        loop = asyncio.get_event_loop()
        
        logger.info("Resolving video metadata and play URL...")
        info = await loop.run_in_executor(
            None, get_douyin_metadata_playwright, url, self.cookie_file_path
        )
        
        logger.info("Downloading MP4 video file...")
        def do_download():
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.douyin.com/'
            }
            cookies = _load_cookies_from_file(self.cookie_file_path)
            with requests.get(info['play_addr'], headers=headers, cookies=cookies, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
                        
        await loop.run_in_executor(None, do_download)
        logger.info(f"Video downloaded successfully to: {dest_path}")
        return info


def auto_generate_douyin_cookies(cookie_file_path: Path) -> bool:
    """Run Playwright headlessly to hit douyin.com and capture signature/session cookies."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            logger.info("Accessing Douyin home page to retrieve cookies...")
            page.goto('https://www.douyin.com/', wait_until='domcontentloaded')
            
            # Wait a bit for Douyin's scripts to generate signature cookies
            time.sleep(3)
            
            cookies = context.cookies()
            has_signature = any(c['name'] == '__ac_signature' for c in cookies)
            if not has_signature:
                logger.info("Waiting for JS evaluation...")
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(3)
                cookies = context.cookies()
                
            browser.close()
            
            # Convert to Netscape format
            with open(cookie_file_path, 'w', encoding='utf-8') as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c['domain']
                    if not domain.startswith('.'):
                        domain = '.' + domain
                    secure = "TRUE" if c.get('secure') else "FALSE"
                    expires = str(int(c.get('expires', 0))) if c.get('expires', -1) > 0 else "0"
                    f.write(f"{domain}\tTRUE\t{c['path']}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")
                    
            logger.info(f"Successfully saved {len(cookies)} cookies to {cookie_file_path}!")
            return True
    except Exception as e:
        logger.error(f"Failed to auto-generate cookies: {e}")
        return False


def export_cookies_from_browser(cookie_file_path: Path) -> bool:
    """Use yt-dlp to extract cookies from various browsers to cookies.txt."""
    browsers = ["chrome", "edge", "firefox", "brave", "opera"]
    for browser in browsers:
        logger.info(f"Trying to export cookies from browser: {browser}...")
        try:
            # We run yt-dlp via subprocess to avoid loading details if not needed
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp",
                 "--cookies-from-browser", browser,
                 "--cookies", str(cookie_file_path),
                 "--skip-download",
                 "https://www.douyin.com/video/7644860524542315776"],
                capture_output=True, text=True, timeout=30
            )
            if cookie_file_path.exists() and cookie_file_path.stat().st_size > 100:
                logger.info(f"Successfully exported cookies from browser '{browser}' to: {cookie_file_path}")
                return True
        except Exception as e:
            logger.warning(f"Failed to export cookies from '{browser}': {e}")
            
    return False
