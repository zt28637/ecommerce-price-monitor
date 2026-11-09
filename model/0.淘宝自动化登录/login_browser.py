# -*- coding: utf-8 -*-
"""登录浏览器（影刀 CodeFlow）：DrissionPage 负责 Edge 的启动 / 复用。

画布契约：
    ensure() -> {
        "ok":       bool,   # 浏览器是否可用
        "launched": bool,   # True=本次新启动；False=复用已有实例
        "detail":   str,    # 人类可读说明
        "port":     int,    # 9223
        "profile":  str,    # 项目 profile 路径
    }

边界（与登录层 README 一致）：
  · 端口 9223 已监听 → 只 attach 验证，不重复启动（避免 profile 锁冲突）。
  · 未监听 → 用固定 profile + 端口启动 Edge；不用无痕、不用无头。
  · 启动参数显式加 --disable-blink-features=AutomationControlled。
  · 打不开就返回 ok=False，由画布告警并终止本轮；本模块不反复重试。

不负责：判活、扫码、Cookie 台账、预算 —— 分别归 classify_login / login_entry。
"""

import json
import os
import socket
import sys
import time

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:                    # 离线编译/单测不装 DP 也能导入
    ChromiumPage = None
    ChromiumOptions = None

PORT = 9223
HOME_URL = "https://www.taobao.com/"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SETTLE_SECONDS = 2                     # 启动后等页面/首个 cookie 稳定，避免判活跑早

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                      # CodeFlow 内联执行时可能没有 __file__
    HERE = ""

_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(HERE, "..", "..")) if HERE else "",
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化",
]


def _first_dir(candidates, required=None):
    """返回第一个存在的目录；required 指定必须存在的相对文件/目录，防止误命中。"""
    for p in candidates:
        if not p or not os.path.isdir(p):
            continue
        if required and not os.path.exists(os.path.join(p, required)):
            continue
        return p
    return ""


# 影刀 CodeFlow 里 HERE=<app>/xbot_robot，HERE/../.. 会是 apps 目录；
# 用 model/ 做标记，确保命中的是仓库根。
PROJECT_V2 = _first_dir(_PROJECT_CANDIDATES, required="model")
PROFILE = os.path.join(PROJECT_V2, "runtime", "profile") if PROJECT_V2 else ""


# ====================================================================== 工具
def _port_open(port=PORT, timeout=1.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _make_options():
    """固定 profile + 端口 + 反自动化标识的启动配置。"""
    co = ChromiumOptions()
    if os.path.exists(EDGE):
        co.set_browser_path(EDGE)
    if PROFILE:
        try:
            os.makedirs(PROFILE, exist_ok=True)
        except OSError:
            pass
        co.set_user_data_path(PROFILE)
    co.set_local_port(PORT)
    # 只消除自动化标识这一层；不做指纹伪装，保持真实 Edge/profile 的一致性
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.headless(False)                 # 4.1.1.4 的 API 是 headless()，不是 set_headless()
    return co


def _result(ok, launched, detail):
    return {
        "ok": bool(ok),
        "launched": bool(launched),
        "detail": detail or "",
        "port": PORT,
        "profile": PROFILE,
    }


# ====================================================================== 入口
def ensure():
    """确保 9223 上有一个可用的 Edge；优先复用，缺了才启动。"""
    if ChromiumPage is None or ChromiumOptions is None:
        return _result(False, False, "DrissionPage 未安装")

    if _port_open(PORT):
        try:
            page = ChromiumPage("127.0.0.1:%d" % PORT)
            _ = page.url                       # 探活：能读 URL 才算可用
            return _result(True, False, "复用已有浏览器")
        except Exception as e:
            return _result(False, False, "端口已开但 attach 失败：%s" % type(e).__name__)

    try:
        page = ChromiumPage(_make_options())
        page.get(HOME_URL)
        time.sleep(SETTLE_SECONDS)
        return _result(True, True, "已启动浏览器")
    except Exception as e:
        return _result(False, False, "启动失败：%s: %s" % (type(e).__name__, e))


def main(args=None):
    """影刀 CodeFlow 入口；画布也可以直接调用 ensure()。"""
    return ensure()


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
