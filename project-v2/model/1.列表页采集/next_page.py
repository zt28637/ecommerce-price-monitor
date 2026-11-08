import random
import time

# ============================================================
# 翻页：点一次「下一页」→ 校验真的翻过去了
# ------------------------------------------------------------
# 核心：点完不校验，就会在旧页上重复采集，而且不报错。
# 判据（任一命中即成功）：
#   · 首张卡片 ID 变化（内容证据）
#   · 页码变成 当前页 + 1（页面自述）
# 10 秒都不变 → no_change，调用方必须停。
#
# 实测注意：页面有两条分页条（顶部吸顶 + 底部），
#           一律取 DOM 里最后一条，否则点到吸顶那条，看似点了但列表不动。
# ============================================================

STATE_JS = r'''
var bars = document.querySelectorAll('.next-pagination-display');
var bar = bars[bars.length - 1];
var cur = 0, total = 0;
if (bar) {
    var em = bar.querySelector('em');
    cur = em ? parseInt(em.textContent) : 0;
    var m = bar.textContent.match(/\/(\d+)/);
    total = m ? parseInt(m[1]) : 0;
}
var btns = document.querySelectorAll('button.next-pagination-item.next-next');
var btn = btns[btns.length - 1];
var hasNext = !!btn && !btn.disabled;
return [cur, total, hasNext];
'''

CLICK_JS = r'''
var btns = document.querySelectorAll('button.next-pagination-item.next-next');
var btn = btns[btns.length - 1];
if (!btn || btn.disabled) return false;
btn.click();
return true;
'''


def _state(page):
    """返回 (当前页, 总页, 是否有下一页)。"""
    value = page.run_js(STATE_JS) or [0, 0, False]
    return int(value[0] or 0), int(value[1] or 0), bool(value[2])


def _first_card(page):
    """当前页第一张卡片的 id，用作内容级校验。"""
    return page.run_js(
        'var a = document.querySelector(\'a[id^="item_id_"]\');'
        'return a ? a.id : "";'
    ) or ""


def turn_next_page(page, timeout=10):
    """点下一页并等它真的翻过去。

    返回 {'ok': bool, 'reason': 'ok'|'last_page'|'no_next'|'click_failed'|'no_change'}
    """
    cur, total, has_next = _state(page)

    if total and cur and cur >= total:
        return {"ok": False, "reason": "last_page"}
    if not has_next:
        return {"ok": False, "reason": "no_next"}

    first_before = _first_card(page)
    time.sleep(random.uniform(3, 8))          # 动作前随机停顿，别做成机械节奏

    if not page.run_js(CLICK_JS):
        return {"ok": False, "reason": "click_failed"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        first_now = _first_card(page)
        cur_now, _, _ = _state(page)

        if (first_before and first_now and first_now != first_before) or \
           (cur and cur_now == cur + 1):
            return {"ok": True, "reason": "ok"}

    return {"ok": False, "reason": "no_change"}


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
