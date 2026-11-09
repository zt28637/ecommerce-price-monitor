# -*- coding: utf-8 -*-
"""节点 0 · 离线回归：classify_login 真值表（page + url 版）。

不依赖浏览器 / 影刀 / Cookie 存储，只验证判据函数本身。
运行：python 测试/login/test_classify_login.py
对应测试记录：T0.1（有效会话）、T0.4（空 tracknick）、T0.5（登录页/风控）
"""
import sys
from pathlib import Path

LOGIN_DIR = Path(__file__).resolve().parents[2] / "0.淘宝自动化登录"
sys.path.insert(0, str(LOGIN_DIR))

from classify_login import classify_login  # noqa: E402


class FakePage:
    """模拟 DrissionPage：run_js 返回 tracknick；run_cdp 返回认证 cookie 名。"""

    def __init__(self, nick=True, confirm=False, pwd=False, raise_js=False,
                 cookies=None):
        self.nick = nick
        self.confirm = confirm
        self.pwd = pwd
        self.raise_js = raise_js
        self.cookies = cookies          # None = CDP 不可用；list = cookie 名

    def run_js(self, *args, **kwargs):
        if self.raise_js:
            raise RuntimeError("js context destroyed")
        return self.nick

    def run_cdp(self, *args, **kwargs):
        if self.cookies is None:
            raise RuntimeError("cdp unavailable")
        # 认证判据现在要求 cookie 有值：淘宝登出常把值置空而保留名字。
        # 传 ("cookie2", "") 这种二元组即"名字在、值为空"。
        out = []
        for c in self.cookies:
            name, value = c if isinstance(c, tuple) else (c, "v")
            out.append({"name": name, "value": value})
        return {"cookies": out}

    def ele(self, locator, *args, **kwargs):
        if locator == ".has-login-title":
            return True if self.confirm else None
        if locator == "text=快速进入":
            return True if self.confirm else None
        if locator in ("#fm-login-password", "#fm-login-id"):
            return True if self.pwd else None
        return None


HOME = "https://www.taobao.com/"
LOGIN = "https://login.taobao.com/member/login.jhtml"
LOGIN_HAVANA = ("https://login.taobao.com/havanaone/login/login.htm"
                "?redirectURL=https%3A%2F%2Fwww.taobao.com%2F")
TMALL = "https://login.tmall.com/"

# (编号, 说明, page, url, 期望)
CASES = [
    ("C01", "首页 + tracknick 非空", FakePage(nick=True), HOME, "auto"),
    ("C02", "首页 + tracknick 空值", FakePage(nick=False), HOME, "not_login"),
    ("C03", "首页 + JS 异常按未登录", FakePage(raise_js=True), HOME, "not_login"),
    ("C04", "登录页 + 确认面板", FakePage(confirm=True), LOGIN, "confirm"),
    ("C05", "登录页 + 密码表单", FakePage(pwd=True), LOGIN, "not_login"),
    ("C06", "登录页 + 无表单无确认", FakePage(), LOGIN, "structure_error"),
    ("C07", "havanaone + 密码表单", FakePage(pwd=True), LOGIN_HAVANA, "not_login"),
    ("C08", "天猫登录页 + 密码表单", FakePage(pwd=True), TMALL, "not_login"),
    ("C09", "风控页优先", FakePage(), "https://sec.taobao.com/x", "risk"),
    ("C10", "url 为 None 不崩", FakePage(nick=True), None, "auto"),
    ("C11", "首页 + 认证 cookie 齐全（tracknick 空）",
     FakePage(nick=False, cookies=["cookie2", "uc1", "unb"]), HOME, "auto"),
    ("C12", "首页 + CDP 只有 tracknick（残留不算登录）",
     FakePage(nick=True, cookies=["tracknick"]), HOME, "not_login"),
    ("C13", "首页 + 只有 cookie2（不足两个）",
     FakePage(nick=False, cookies=["cookie2"]), HOME, "not_login"),
    ("C14", "首页 + CDP 异常回退 tracknick",
     FakePage(nick=True, cookies=None), HOME, "auto"),
    ("C15", "首页 + cookie 名在但值为空（登出残留）算未登录",
     FakePage(nick=True, cookies=[("cookie2", ""), ("unb", "")]), HOME, "not_login"),
    ("C16", "首页 + cookie2 有值、另一个为空 → 不足两个有效",
     FakePage(nick=False, cookies=[("cookie2", "v"), ("unb", "")]), HOME, "not_login"),
]


def main() -> int:
    failed = 0
    for cid, desc, page, url, expect in CASES:
        actual = classify_login(page, url)
        ok = actual == expect
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {cid} {desc}: "
              f"expect={expect} actual={actual}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
