# -*- coding: utf-8 -*-
"""节点 0 · 离线回归：login_browser.ensure（不启动真实浏览器）。

运行：python "project-v2/model/测试/login/test_login_browser.py"
"""
import os
import sys
import tempfile
from pathlib import Path

LOGIN_DIR = Path(__file__).resolve().parents[2] / "0.淘宝自动化登录"
sys.path.insert(0, str(LOGIN_DIR))

import login_browser as lb  # noqa: E402

_TOTAL = 0


def case(name, actual, expect):
    global _TOTAL
    _TOTAL += 1
    ok = actual == expect
    print(f"{'PASS' if ok else 'FAIL'} {name}: expect={expect} actual={actual}")
    return 0 if ok else 1


class FakeOptions:
    instances = []

    def __init__(self):
        self.browser_path = None
        self.profile = None
        self.port = None
        self.args = []
        self.headless_value = None
        FakeOptions.instances.append(self)

    def set_browser_path(self, p):
        self.browser_path = p

    def set_user_data_path(self, p):
        self.profile = p

    def set_local_port(self, p):
        self.port = p

    def set_argument(self, a):
        self.args.append(a)

    def headless(self, v):
        self.headless_value = v


class FakePage:
    def __init__(self, target=None):
        self.target = target
        self.url = "https://www.taobao.com/"
        self.got = []

    def get(self, url):
        self.got.append(url)


def main() -> int:
    failed = 0
    names = ("ChromiumPage", "ChromiumOptions", "_port_open", "PROFILE",
             "_make_options", "SETTLE_SECONDS")
    orig = {n: getattr(lb, n) for n in names}
    td = tempfile.mkdtemp()
    lb.PROFILE = td
    lb.SETTLE_SECONDS = 0
    try:
        # LB01 端口已开 + attach 成功 → 复用
        lb._port_open = lambda *a, **k: True
        lb.ChromiumPage = lambda target=None: FakePage(target)
        res = lb.ensure()
        failed += case("LB01 复用浏览器", (res["ok"], res["launched"]), (True, False))

        # LB02 端口已开 + attach 失败 → 不重复启动
        def _bad_page(target=None):
            raise RuntimeError("attach fail")
        lb.ChromiumPage = _bad_page
        res = lb.ensure()
        failed += case("LB02 attach 失败", (res["ok"], res["launched"]), (False, False))

        # LB03 端口关闭 + 启动成功 → launched=True，参数齐全
        lb._port_open = lambda *a, **k: False
        FakeOptions.instances = []
        lb.ChromiumOptions = FakeOptions
        lb.ChromiumPage = lambda target=None: FakePage(target)
        res = lb.ensure()
        co = FakeOptions.instances[-1]
        failed += case("LB03 启动浏览器", (res["ok"], res["launched"]), (True, True))
        failed += case("LB04 禁用自动化标识",
                       "--disable-blink-features=AutomationControlled" in co.args, True)
        failed += case("LB05 固定 profile", co.profile, td)
        failed += case("LB06 固定端口", co.port, lb.PORT)
        failed += case("LB07 非无头", co.headless_value, False)

        # LB08 启动失败 → ok=False
        def _bad_launch(target=None):
            raise RuntimeError("launch fail")
        lb.ChromiumPage = _bad_launch
        res = lb.ensure()
        failed += case("LB08 启动失败", (res["ok"], res["launched"]), (False, False))

        # LB09 DP 未安装
        lb.ChromiumPage = None
        lb.ChromiumOptions = None
        res = lb.ensure()
        failed += case("LB09 DP 未安装", res["ok"], False)
    finally:
        for n, v in orig.items():
            setattr(lb, n, v)
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    print(f"\n{_TOTAL - failed}/{_TOTAL} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
