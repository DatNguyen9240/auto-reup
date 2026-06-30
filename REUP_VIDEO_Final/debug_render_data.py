import requests, re, urllib.request, urllib.parse

url = 'https://v.douyin.com/xJK9LqMZZNc/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
with urllib.request.urlopen(req, timeout=10) as resp:
    url = resp.url

page_resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

print('Page length:', len(page_resp.text))

match = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', page_resp.text, re.DOTALL)
if match:
    data = urllib.parse.unquote(match.group(1))
    print('Found RENDER_DATA')
    print('Data snippet:', data[:500])
else:
    print('No RENDER_DATA found')
