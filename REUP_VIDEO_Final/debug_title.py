import requests, re, urllib.request

url = 'https://v.douyin.com/xJK9LqMZZNc/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
with urllib.request.urlopen(req, timeout=10) as resp:
    url = resp.url

page_resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
title_match = re.search(r'<title>(.*?)</title>', page_resp.text)
if title_match:
    print('Title from tag:', title_match.group(1))

import json
for match in re.finditer(r'\{[^{]*?"desc":"(.*?)"[^}]*?\}', page_resp.text):
    print('Found potential JSON:', match.group(0)[:100])
