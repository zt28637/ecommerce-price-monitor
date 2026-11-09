"""页面风控 / 登录墙识别（列表层、详情层共用）。

为什么要有这一层：
  采集页拿不到卡片时，"没结果"和"被拦住"在代码里长得一样——都是 0 张卡。
  若直接抛 ElementNotFound，上游只能看到一句 XPath 超时，看不出该重试、
  该换 IP、还是该重新登录。这里把"拦住"和"空结果"分开，给可读 reason。

判据三档（任一命中即认定为被拦，按 URL -> 文本 -> DOM 的顺序）：
  1. URL   ：跳到登录域 = 未登录；命中 sec.taobao.com / punish / x5sec = 风控
  2. 文本  ：滑块、人机验证、"访问过于频繁"等提示语
  3. DOM   ：淘宝滑块容器 #nc_1_n1z / .nc-container、baxia 弹窗、验证码 iframe
  DOM 判据要过滤"存在但不可见"的节点，否则页面里预留的隐藏容器会造成误报。
"""

import json

LOGIN_URL_MARKERS = ("login.taobao.com", "login.tmall.com")
RISK_URL_MARKERS = ("sec.taobao.com", "_____tmd_____", "punish", "x5sec", "captcha")
RISK_TEXT_MARKERS = ("请拖动滑块", "滑块验证", "安全验证", "人机验证", "访问受限",
                     "哎哟喂", "系统繁忙", "请稍后再试", "访问过于频繁", "Too Many Requests")
RISK_DOM_SELECTOR = ("#nc_1_n1z, .nc-container, #baxia-dialog, "
                     "[id*=captcha], iframe[src*=captcha]")


def _page_url(page):
    try:
        return (getattr(page, "url", "") or "").lower()
    except Exception:
        return ""


def _body_text(page, limit=5000):
    try:
        return page.run_js(
            "return document.body ? document.body.innerText.slice(0,%d) : ''" % limit) or ""
    except Exception:
        return ""


def _visible_dom_hit(page, selector=RISK_DOM_SELECTOR):
    """选择器命中且元素真实可见（排除预留的隐藏容器）。

    可见性用 getClientRects 而不是 offsetParent：淘宝滑块/弹窗常用
    position:fixed，而 fixed 元素的 offsetParent 恒为 null —— 用 offsetParent
    会把真正的风控弹层判成"不可见"，风险页识别直接失效。
    """
    try:
        return bool(page.run_js(
            "var e=document.querySelector(%s);"
            "if(!e || !e.getClientRects().length) return false;"
            "var s=getComputedStyle(e);"
            "return s.display!=='none' && s.visibility!=='hidden';"
            % json.dumps(selector)))
    except Exception:
        return False


def block_reason(page):
    """被拦就返回 (reason, 证据)，没被拦返回 None。

    reason: 'not_login' | 'risk_page'
    证据串形如 'url:sec.taobao.com' / 'text:请拖动滑块' / 'dom:#nc_1_n1z, ...'
    """
    url = _page_url(page)
    for m in LOGIN_URL_MARKERS:
        if m in url:
            return "not_login", "url:%s" % m
    for m in RISK_URL_MARKERS:
        if m in url:
            return "risk_page", "url:%s" % m
    text = _body_text(page)
    for m in RISK_TEXT_MARKERS:
        if m in text:
            return "risk_page", "text:%s" % m
    if _visible_dom_hit(page):
        return "risk_page", "dom:%s" % RISK_DOM_SELECTOR
    return None


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
