import requests, re, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import pipeline

cookies_file = Path(__file__).parent / 'cookies.txt'
cookies = pipeline._load_cookies_from_file(cookies_file)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Referer': 'https://www.douyin.com/',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

sess = requests.Session()
sess.headers.update(headers)
sess.cookies.update(cookies)

resp = sess.get('https://www.douyin.com/video/7644860524542315776', timeout=15)

# Find all script tags with JSON
script_matches = re.findall(r'<script[^>]*>(\{.{100,}?\})</script>', resp.text[:100000], re.DOTALL)
print(f'Script JSON blocks found: {len(script_matches)}')
for i, s in enumerate(script_matches[:3]):
    print(f'Block {i}: {s[:200]}\n')

# Check for desc in a different way
for idx in range(len(resp.text)):
    if resp.text[idx:idx+6] == '"desc"':
        print('Found desc at', idx)
        print(repr(resp.text[idx:idx+200]))
        print()
        break
