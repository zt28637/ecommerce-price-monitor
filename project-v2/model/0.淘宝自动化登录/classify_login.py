try:
    import xbot
except ImportError:
    xbot = None
try:
    from DrissionPage import ChromiumPage
except ImportError:
    ChromiumPage = None

LOGIN_HOSTS = ("login.taobao.com", "login.tmall.com")
AUTH_COOKIES = ("cookie2", "uc1", "_nk_", "unb", "cookie1")


def _nick_ok(page):
    """页面 Cookie 里 tracknick 是否有非空值（空值/不存在都算未登录）。"""
    try:
        return bool(page.run_js("return /(?:^|; )tracknick=[^;]+/.test(document.cookie)"))
    except Exception:
        return False


def _auth_cookies(page):
    """返回 taobao 域下命中的认证 cookie 名集合；CDP 读不到时返回 None。"""
    try:
        data = page.run_cdp("Network.getCookies",
                            urls=["https://www.taobao.com/"])
        names = {c.get("name") for c in (data or {}).get("cookies", [])}
        return names & set(AUTH_COOKIES)
    except Exception:
        return None


def auth_ok(page):
    """会话有效性：CDP 可用时以认证 cookie 为准，读不到才退回 tracknick。

    tracknick 可能是登出后残留的旧值，不能单独作为登录依据；
    cookie2 是淘宝主会话 cookie，要求它 + 至少一个其它认证 cookie。
    """
    hits = _auth_cookies(page)
    if hits is None:
        return _nick_ok(page)
    return "cookie2" in hits and len(hits) >= 2


def classify_login(page, url) -> str:

    url = url or ""

    # 淘宝拦截
    if "sec.taobao.com" in url:
        return "risk"

    # 已离开登录域：按 Cookie 复核，避免 URL 假成功
    if not any(h in url for h in LOGIN_HOSTS):
        return "auto" if auth_ok(page) else "not_login"

    # 仍在登录域：确认面板 / 密码表单
    if page.ele(".has-login-title", timeout=2) and page.ele("text=快速进入", timeout=2):
        return "confirm"
    if page.ele("#fm-login-password", timeout=2) or page.ele("#fm-login-id", timeout=2):
        return "not_login"
    return "structure_error"

def main(url):
    if ChromiumPage is None:
        return "structure_error"
    page = ChromiumPage("127.0.0.1:9223")
    probe_state = classify_login(page, url)
    if xbot is not None:
        xbot.app.logging.info("login_gate: %s" % probe_state)
    return probe_state