# -*- coding: utf-8 -*-
"""节点 0 · 离线回归：login_entry 预算/冷却/动作决策矩阵。

不依赖浏览器 / 影刀 / 网络，只验证纯决策函数与台账读写。
运行：python "project-v2/model/测试/login/test_login_entry.py"
"""
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

LOGIN_DIR = Path(__file__).resolve().parents[2] / "0.淘宝自动化登录"
sys.path.insert(0, str(LOGIN_DIR))

import login_entry as le  # noqa: E402

NOW = datetime.datetime(2026, 11, 7, 23, 30, 0)


def dt(hours=0, days=0):
    return NOW - datetime.timedelta(hours=hours, days=days)


_TOTAL = 0


def case(name, actual, expect):
    global _TOTAL
    _TOTAL += 1
    ok = actual == expect
    print(f"{'PASS' if ok else 'FAIL'} {name}: expect={expect} actual={actual}")
    return 0 if ok else 1


def main() -> int:
    failed = 0

    # ---- budget_decision ----
    failed += case("B01 空台账允许", le.budget_decision(NOW, {})["reason"], "ok")
    failed += case("B02 已登录不算预算",
                   le.budget_decision(NOW, {}, need_real_login=False)["reason"],
                   "already_logged_in")
    failed += case("B03 1h 前登录过 → 拦截",
                   le.budget_decision(NOW, {"last_login_at": le._iso(dt(hours=1))})["reason"],
                   "budget_24h")
    failed += case("B04 25h 前登录过 → 允许",
                   le.budget_decision(NOW, {"last_login_at": le._iso(dt(hours=25))})["reason"],
                   "ok")
    failed += case("B05 冷却中 → 拦截",
                   le.budget_decision(NOW, {"cooldown_until": le._iso(dt(hours=-2))})["reason"],
                   "cooldown")
    failed += case("B06 同日被踢 2 次 → 停跑",
                   le.budget_decision(NOW, {"kick_count": 2,
                                           "kick_date": NOW.strftime("%Y-%m-%d")})["reason"],
                   "kicked_twice")
    failed += case("B07 昨天被踢 2 次 → 允许",
                   le.budget_decision(NOW, {"kick_count": 2, "kick_date": "2026-11-06"})["reason"],
                   "ok")

    # ---- decide_action ----
    allow = {"allow": True}
    block = {"allow": False, "reason": "budget_24h"}
    failed += case("A01 auto", le.decide_action("auto", allow, True), "already_logged_in")
    failed += case("A02 confirm", le.decide_action("confirm", allow, True), "quick_enter")
    failed += case("A03 risk", le.decide_action("risk", allow, True), "cold_down")
    failed += case("A04 not_login + 允许 + 有凭据",
                   le.decide_action("not_login", allow, True), "password")
    failed += case("A05 not_login + 允许 + 无凭据",
                   le.decide_action("not_login", allow, False), "manual")
    failed += case("A06 not_login + 拦截 → 人工",
                   le.decide_action("not_login", block, True), "manual")
    failed += case("A07 structure_error → 人工",
                   le.decide_action("structure_error", allow, True), "manual")

    # ---- 台账状态迁移 ----
    st = le._empty_state()
    st = le.record_kick(NOW, st)
    failed += case("K01 第一次被踢计数", st["kick_count"], 1)
    st = le.record_kick(NOW, st)
    failed += case("K02 同日第二次被踢计数", st["kick_count"], 2)
    failed += case("K03 被踢后写入冷却", bool(st["cooldown_until"]), True)

    st2 = le.record_kick(NOW + datetime.timedelta(days=1), st)
    failed += case("K04 跨日重置计数", st2["kick_count"], 1)

    st_same_day = le.record_kick(NOW, le.record_kick(NOW, le._empty_state()))
    st3 = le.record_login(NOW, st_same_day, "password")
    failed += case("K05 同日登录保留踢计数", st3["kick_count"], 2)
    failed += case("K06 登录成功清冷却", st3["cooldown_until"], "")
    failed += case("K07 登录成功写时间", st3["last_login_at"], le._iso(NOW))

    st4 = le.record_login(NOW + datetime.timedelta(days=2), st, "manual")
    failed += case("K08 跨日登录清踢计数", st4["kick_count"], 0)

    # ---- 时间解析 ----
    failed += case("T01 ISO → datetime", le._parse(le._iso(NOW)), NOW)
    failed += case("T02 空值 → None", le._parse(""), None)
    failed += case("T03 坏值 → None", le._parse("not-a-time"), None)

    # ---- mark_login 落台账（临时文件） ----
    old_state, old_dir = le.STATE_PATH, le.TB_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            le.TB_DIR = td
            le.STATE_PATH = os.path.join(td, "login_state.json")
            out = le.mark_login("manual")
            saved = le._load_state()
            failed += case("M01 mark_login 返回 ok", out["ok"], True)
            failed += case("M02 台账写入 method", saved.get("last_login_method"), "manual")
            failed += case("M03 台账写入时间", bool(saved.get("last_login_at")), True)
    finally:
        le.STATE_PATH, le.TB_DIR = old_state, old_dir

    # ---- 画布契约字段 ----
    res = le._result("cold_down", "", "manual_required", need_manual=True)
    for key in ("state", "method", "result", "need_manual", "need_qr", "stop",
                "login_at", "budget", "detail"):
        failed += case(f"R-{key} 字段存在", key in res, True)
    failed += case("R-need_qr 兼容", res["need_qr"], True)

    # ---- 编排：_main 分支（monkeypatch，不碰浏览器） ----
    failed += _test_orchestration()

    # ---- 人工登录等待（假 page，不碰浏览器） ----
    failed += _test_wait_manual()

    # ---- IO / 告警 / 兜底 ----
    failed += _test_io_and_alert()

    print(f"\n{_TOTAL - failed}/{_TOTAL} passed")
    return 1 if failed else 0


class FakePage:
    def __init__(self):
        self.url = "https://login.taobao.com/member/login.jhtml"

    def run_js(self, *args, **kwargs):
        return True

    def run_cdp(self, *args, **kwargs):
        return {"cookies": []}


def _test_orchestration():
    """用假 page / 假 classify 验证 _main 的分流，不依赖真实浏览器。"""
    failed = 0
    names = ("_attach", "alert", "_read_cred", "_fill_and_submit", "_quick_enter",
             "_wait_leave_login", "_write_run_log", "_failure_reason", "ALLOW_PASSWORD")
    orig = {n: getattr(le, n) for n in names}
    orig_classify = le.classify_login.classify_login
    orig_nick = le.classify_login._nick_ok
    orig_auth = le.classify_login.auth_ok
    old_settle = le.SETTLE_TIMEOUT
    le.SETTLE_TIMEOUT = 0
    le.classify_login.auth_ok = lambda p: False
    old_state_path = le.STATE_PATH
    td = tempfile.mkdtemp()
    le.STATE_PATH = os.path.join(td, "login_state.json")
    le._write_run_log = lambda *a, **k: None
    captured = []
    le.alert = lambda text, title="": (captured.append(text), {"status": "skipped"})[1]
    try:
        # O01 浏览器不可用：停跑并告警
        captured.clear()
        le._attach = lambda: (None, "browser_down")
        res = le._main()
        failed += case("O01 browser_down 停跑", res["stop"], True)
        failed += case("O02 browser_down 告警", bool(captured), True)

        # O03 已登录：auto 不消耗预算
        le._attach = lambda: (FakePage(), "")
        le.classify_login.classify_login = lambda p, u: "auto"
        res = le._main()
        failed += case("O03 auto → logged_in", (res["state"], res["method"]), ("logged_in", "auto"))

        # O04 确认面板 + 快速进入成功
        le.classify_login.classify_login = lambda p, u: "confirm"
        le._quick_enter = lambda p: "ok"
        le._wait_leave_login = lambda p, s: "https://www.taobao.com/"
        le.classify_login._nick_ok = lambda p: True
        res = le._main()
        failed += case("O04 快速进入成功", (res["state"], res["method"]), ("logged_in", "quick_enter"))

        # O05 确认面板 + 快速进入失败 → 人工
        le._quick_enter = lambda p: "not_found"
        res = le._main()
        failed += case("O05 快速进入失败转人工", (res["result"], res["need_manual"]),
                       ("manual_required", True))

        # O06 24h 内登录过又失效 → budget_blocked，不自动填账密
        now = datetime.datetime.now()
        le._save_state({"last_login_at": le._iso(now - datetime.timedelta(hours=1)),
                        "kick_count": 0, "kick_date": ""})
        le.classify_login.classify_login = lambda p, u: "not_login"
        le._read_cred = lambda: ("u", "p")
        called = {"fill": False}

        def _no_fill(*a, **k):
            called["fill"] = True
            return "ok"
        le._fill_and_submit = _no_fill
        res = le._main()
        failed += case("O06 预算拦截结果", res["result"], "budget_blocked")
        failed += case("O07 预算拦截不填账密", called["fill"], False)
        failed += case("O08 预算拦截转人工", res["need_manual"], True)
        failed += case("O09 被踢计数 +1", le._load_state().get("kick_count"), 1)

        # O10 预算允许 + 账密成功 → logged_in，并写台账（显式打开账密开关）
        le.ALLOW_PASSWORD = True
        if os.path.exists(le.STATE_PATH):
            os.remove(le.STATE_PATH)
        seq = iter(["not_login", "auto"])
        le.classify_login.classify_login = lambda p, u: next(seq)
        le._fill_and_submit = lambda *a, **k: "ok"
        le._wait_leave_login = lambda p, s: "https://www.taobao.com/"
        res = le._main()
        failed += case("O10 账密成功", (res["state"], res["method"]), ("logged_in", "password"))
        failed += case("O11 账密成功写台账", bool(le._load_state().get("last_login_at")), True)

        # O12 页面结构异常：直接人工，不消耗预算、不记被踢
        le._save_state({"last_login_at": le._iso(datetime.datetime.now()
                                                 - datetime.timedelta(hours=1)),
                        "kick_count": 0, "kick_date": ""})
        le.classify_login.classify_login = lambda p, u: "structure_error"
        res = le._main()
        failed += case("O12 结构异常转人工", (res["result"], res["need_manual"]),
                       ("structure_error", True))
        failed += case("O13 结构异常不记被踢", le._load_state().get("kick_count"), 0)

        # O14 账密遇验证码 → 人工
        if os.path.exists(le.STATE_PATH):
            os.remove(le.STATE_PATH)
        le.classify_login.classify_login = lambda p, u: "not_login"
        le._read_cred = lambda: ("u", "p")
        le._fill_and_submit = lambda *a, **k: "captcha"
        res = le._main()
        failed += case("O14 验证码转人工", (res["result"], res["need_manual"]),
                       ("captcha", True))

        # O15 账密提交后滑块 → 人工
        le._fill_and_submit = lambda *a, **k: "ok"
        le._wait_leave_login = lambda p, s: "https://login.taobao.com/x"
        le._failure_reason = lambda p: "slider"
        res = le._main()
        failed += case("O15 滑块转人工", (res["result"], res["need_manual"]),
                       ("slider", True))

        # O16 默认关闭账密：not_login + 有凭据 → 人工，不填表
        le.ALLOW_PASSWORD = False
        if os.path.exists(le.STATE_PATH):
            os.remove(le.STATE_PATH)
        le.classify_login.classify_login = lambda p, u: "not_login"
        le._read_cred = lambda: ("u", "p")
        called2 = {"fill": False}

        def _no_fill2(*a, **k):
            called2["fill"] = True
            return "ok"
        le._fill_and_submit = _no_fill2
        res = le._main()
        failed += case("O16 默认转人工", (res["result"], res["need_manual"]),
                       ("manual_required", True))
        failed += case("O17 默认不填表", called2["fill"], False)

        # O18 会话有效但页面判成 not_login → 按 auto 处理（不误转人工）
        le.classify_login.classify_login = lambda p, u: "not_login"
        le.classify_login.auth_ok = lambda p: True
        res = le._main()
        failed += case("O18 认证 cookie 覆盖误判",
                       (res["state"], res["method"]), ("logged_in", "auto"))
    finally:
        for n, v in orig.items():
            setattr(le, n, v)
        le.classify_login.classify_login = orig_classify
        le.classify_login._nick_ok = orig_nick
        le.classify_login.auth_ok = orig_auth
        le.SETTLE_TIMEOUT = old_settle
        le.STATE_PATH = old_state_path
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    return failed


class FakeWaitPage:
    """模拟 wait_manual 需要的 page：url 按序列返回，其余空实现。"""

    def __init__(self, urls):
        self._urls = list(urls)
        self._i = 0
        self.got = []
        self.shots = []

    @property
    def url(self):
        i = min(self._i, len(self._urls) - 1)
        self._i += 1
        return self._urls[i]

    def get(self, url):
        self.got.append(url)

    def ele(self, locator, *args, **kwargs):
        return None

    def get_frames(self):
        return []

    def get_screenshot(self, path=None, **kwargs):
        self.shots.append(path)


class FakeQrElement:
    def __init__(self):
        self.shots = []

    def get_screenshot(self, path=None, **kwargs):
        self.shots.append(path)


class FakeQrPage(FakeWaitPage):
    def __init__(self, urls, qr=True):
        super().__init__(urls)
        self.qr = qr

    def ele(self, locator, *args, **kwargs):
        return FakeQrElement() if self.qr else None


def _test_wait_manual():
    """wait_manual：成功 / 超时 / 浏览器不可用 / 二维码截图，全部用假 page。"""
    failed = 0
    names = ("_attach", "alert", "_write_run_log", "_capture_qr")
    orig = {n: getattr(le, n) for n in names}
    orig_auth = le.classify_login.auth_ok
    old_state_path, old_qr_dir, old_poll = le.STATE_PATH, le.QR_DIR, le.WAIT_POLL
    td = tempfile.mkdtemp()
    le.STATE_PATH = os.path.join(td, "login_state.json")
    le.QR_DIR = os.path.join(td, "login")
    le.WAIT_POLL = 0
    le._write_run_log = lambda *a, **k: None
    le.alert = lambda *a, **k: {"status": "skipped"}
    try:
        login = "https://login.taobao.com/member/login.jhtml"
        home = "https://www.taobao.com/"

        # W01 成功：入口未登录，轮询期间变为已登录
        calls = {"n": 0}

        def _auth_after_entry(p):
            calls["n"] += 1
            return calls["n"] > 1

        page = FakeWaitPage([login, login, home, home])
        le._attach = lambda: (page, "")
        le._capture_qr = lambda p: os.path.join(td, "qr.png")
        le.classify_login.auth_ok = _auth_after_entry
        res = le.wait_manual(timeout=5)
        failed += case("W01 人工成功", (res["state"], res["method"], res["result"]),
                       ("logged_in", "manual", "ok"))
        failed += case("W02 写真实登录时间", bool(le._load_state().get("last_login_at")), True)

        # W03 超时：一直停在登录页
        page = FakeWaitPage([login])
        le._attach = lambda: (page, "")
        le.classify_login.auth_ok = lambda p: False
        res = le.wait_manual(timeout=0)
        failed += case("W03 人工超时", (res["result"], res["stop"]), ("timeout", True))

        # W04 浏览器不可用
        le._attach = lambda: (None, "browser_down")
        res = le.wait_manual(timeout=0)
        failed += case("W04 浏览器不可用", (res["result"], res["stop"]),
                       ("browser_down", True))

        # W07 入口已登录 → auto，不写 last_login_at（不算真实登录）
        if os.path.exists(le.STATE_PATH):
            os.remove(le.STATE_PATH)
        page = FakeWaitPage([home, home])
        le._attach = lambda: (page, "")
        le.classify_login.auth_ok = lambda p: True
        res = le.wait_manual(timeout=0)
        failed += case("W07 入口已登录", (res["state"], res["method"]),
                       ("logged_in", "auto"))
        failed += case("W08 不写真实登录时间",
                       bool(le._load_state().get("last_login_at")), False)

        # W05 二维码元素截图（用真实 _capture_qr）
        le._capture_qr = orig["_capture_qr"]
        page = FakeQrPage([login], qr=True)
        path = le._capture_qr(page)
        failed += case("W05 二维码截图路径", bool(path) and path.endswith(".png"), True)

        # W06 找不到二维码 → 整页截图兜底
        page = FakeQrPage([login], qr=False)
        path = le._capture_qr(page)
        failed += case("W06 整页截图兜底", bool(path) and path.endswith(".png"), True)
    finally:
        for n, v in orig.items():
            setattr(le, n, v)
        le.classify_login.auth_ok = orig_auth
        le.STATE_PATH, le.QR_DIR, le.WAIT_POLL = old_state_path, old_qr_dir, old_poll
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    return failed


def _test_io_and_alert():
    """告警回退、凭据解析、run_log 落盘、main 兜底。"""
    failed = 0
    names = ("_send_via", "alert", "_main", "_write_run_log")
    orig = {n: getattr(le, n) for n in names}
    old_cred, old_proj, old_state = le.CRED_PATH, le.PROJECT_V2, le.STATE_PATH
    td = tempfile.mkdtemp()
    try:
        # N01-N04 告警回退
        calls = []
        le._send_via = lambda name, text, title: (calls.append(name),
                                                  {"status": "skipped"})[1]
        res = le.alert("x")
        failed += case("N01 两渠道都跳过", res.get("status"), "skipped")
        failed += case("N02 两渠道都尝试", calls, ["feishu_notify", "dingtalk_notify"])

        calls.clear()
        le._send_via = lambda name, text, title: (calls.append(name),
                                                  {"status": "ok"})[1]
        res = le.alert("x")
        failed += case("N03 飞书成功即返回", (res.get("status"), calls),
                       ("ok", ["feishu_notify"]))

        calls.clear()

        def _feishu_fail(name, text, title):
            calls.append(name)
            if name == "feishu_notify":
                raise RuntimeError("feishu down")
            return {"status": "ok"}
        le._send_via = _feishu_fail
        res = le.alert("x")
        failed += case("N04 飞书异常回退钉钉", (res.get("status"), calls),
                       ("ok", ["feishu_notify", "dingtalk_notify"]))

        # N05-N07 凭据解析
        cred_path = os.path.join(td, "cred.txt")
        le.CRED_PATH = cred_path
        with open(cred_path, "w", encoding="utf-8") as f:
            f.write("user\npass\n")
        failed += case("N05 凭据两行", le._read_cred(), ("user", "pass"))
        with open(cred_path, "w", encoding="utf-8") as f:
            f.write("user\n")
        failed += case("N06 凭据单行", le._read_cred(), None)
        os.remove(cred_path)
        failed += case("N07 凭据缺失", le._read_cred(), None)

        # N08 run_log 落盘且可解析
        le.PROJECT_V2 = td
        le._write_run_log({"state": "logged_in", "result": "ok"},
                          {"reason": "ok"}, {}, {"last_state": "logged_in"})
        log_dir = os.path.join(td, "runtime", "run_log", "login")
        files = os.listdir(log_dir) if os.path.isdir(log_dir) else []
        failed += case("N08 run_log 生成", len(files), 1)
        if files:
            with open(os.path.join(log_dir, files[0]), encoding="utf-8") as f:
                payload = json.load(f)
            failed += case("N09 run_log 内容", payload["result"]["state"], "logged_in")

        # N10 结果可 JSON 序列化
        try:
            json.dumps(le._result("cold_down", "", "manual_required", need_manual=True))
            ok = True
        except TypeError:
            ok = False
        failed += case("N10 结果可序列化", ok, True)

        # N11 main 兜底：内部异常不裸抛
        le.STATE_PATH = os.path.join(td, "state.json")
        le._write_run_log = lambda *a, **k: None
        le._main = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        res = le.main()
        failed += case("N11 main 兜底", (res["result"], res["stop"]),
                       ("structure_error", True))
    finally:
        for n, v in orig.items():
            setattr(le, n, v)
        le.CRED_PATH, le.PROJECT_V2, le.STATE_PATH = old_cred, old_proj, old_state
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
