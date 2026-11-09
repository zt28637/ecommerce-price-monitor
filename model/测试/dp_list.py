import time
from pathlib import Path

from DrissionPage import ChromiumPage

KEYWORD = "男士长袖"          
OUT_DIR = Path(r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\runtime\samples")

page = ChromiumPage("127.0.0.1:9223")

page.get(f"https://s.taobao.com/search?q={KEYWORD}")
time.sleep(2)

# 被踢到登录页就别往下走了，存下来的也是废样本
if "login.taobao.com" in page.url:
    raise SystemExit(f"未登录，被重定向到：{page.url}")

before = len(page.html)
print(f"滚动前字符数：{before}")

# 懒加载：边滚边出卡片，滚到底再取
for i in range(15):
    page.scroll.down(800)
    time.sleep(1)

html = page.html

OUT_DIR.mkdir(parents=True, exist_ok=True)
out = OUT_DIR / f"list_{KEYWORD}_{time.strftime('%Y%m%d_%H%M%S')}.html"
out.write_text(html, encoding="utf-8")

# 写盘后必须重读验证：字符数一致才算没截断/没编码损坏
back = out.read_text(encoding="utf-8")

print(f"滚动后字符数：{len(html)}")
print(f"回读字符数  ：{len(back)}")
print(f"回读一致    ：{len(html) == len(back)}")
print(f"商品卡片数  ：{html.count('mainPicAndDesc--')}")
print(f"URL         ：{page.url}")
print(f"落盘        ：{out}")
