import random, time

def _card_ids(page):
    """返回当前列表页所有卡片的 ID 集合"""
    return page.run_js(
        'return Array.from(document.querySelectorAll(\'a[id^="item_id_"]\'))'
        '.map(e => e.id.replace("item_id_", ""));'
    ) or []

def distance_to_bottom(page):
    """返回当前视口底部到页面底部的距离"""
    return page.run_js('return document.documentElement.scrollHeight - window.innerHeight - window.scrollY')

def human_scroll(page):
    # ① 步长随机：300~800px
    step = random.randint(300, 800)
    page.run_js("window.scrollBy(0, %d);" % step)

    # ② 停顿随机：0.6~1.8 秒
    time.sleep(random.uniform(0.6, 1.8))

    # ③ 方向随机：15% 概率往回滚一点
    if random.random() < 0.15:
        back = random.randint(100, 200)
        page.run_js("window.scrollBy(0, -%d);" % back)
        time.sleep(random.uniform(0.3, 0.8))
# ============================================================
# 滚动到底
# ------------------------------------------------------------
# 初始化：
#   cards_prev = 筛选后稳定下来的卡片集合
#   still      = 0
#   reached    = False
#
# 循环最多 20 轮，每轮：
#   1. 算距底像素
#   2. 如果距底 <= 200：
#        取当前卡片集合 ids_now
#        ids_now 非空且等于 cards_prev → still + 1
#        否则                          → still = 0
#        still >= 2 → 打印卡片数和轮数，reached = True，break
#        cards_prev = ids_now
#      否则：
#        still = 0
#   3. 调用 human_scroll(page) 随机滚动一次
#   4. cards_prev = 当前卡片集合
#
# 循环结束后：
#   如果 reached 仍为 False → 打印距底距离和卡片数（20 轮没到底）
# ============================================================
def scroll_to_bottom(page, _card_ids):
    """滚动到底，返回是否到底"""
    cards_prev = set(_card_ids(page))
    still = 0
    reached = False

    for i in range(1, 21):
        if distance_to_bottom(page) <= 200:
            ids_now = set(_card_ids(page))
            if ids_now and ids_now == cards_prev:
                still += 1
            else:
                still = 0
            if still >= 2:
                print("到底了，卡片数=%d，轮数=%d" % (len(ids_now), i))
                reached = True
                cards_prev = ids_now
                break
            cards_prev = ids_now
        else:
            still = 0

        human_scroll(page)
        cards_prev = set(_card_ids(page))

    if not reached:
        print("20 轮还没到底，距底 %dpx，卡片数=%d（可能是半渲染，别直接落盘）"
              % (distance_to_bottom(page), len(cards_prev)))
    return reached


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
