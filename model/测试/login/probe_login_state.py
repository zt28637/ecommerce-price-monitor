# -*- coding: utf-8 -*-
"""节点 0 · 登录页判活实机探针（只读，不提交任何登录）。

验证蓝图 §3 的 A 判活 / B 快速进入 两支，以及测试记录 §3.3 的待实测疑点。
不写自定义数据、不点击密码登录、不消耗登录预算。

用法：
    python 测试/login/probe_login_state.py                 # 打开带 redirectURL 的登录页
    python 测试/login/probe_login_state.py --no-redirect   # 打开不带 redirectURL 的登录页
    python 测试/login/probe_login_state.py --click-quick-enter
    python 测试/login/probe_login_state.py --keep-tab

前置：Edge 已以 `--remote-debugging-port=9223 --user-data-dir=runtime/profile` 启动。
输出：runtime/_sample/login_scan/<时间戳>/probe_result.json + page.html
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from DrissionPage import ChromiumPage

ROOT = Path(__file__).resolve().parents[3]          # 
OUT_ROOT = ROOT / "runtime" / "_sample" / "login_scan"
LOGIN_URL = "https://login.taobao.com/member/login.jhtml"
REDIRECT = "https://www.taobao.com/"
LOGIN_HOSTS = ("login.taobao.com", "login.tmall.com")

SNAPSHOT_JS = r"""
function () {
  const vis = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const txt = el => (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const q = s => Array.from(document.querySelectorAll(s));
  const pick = s => q(s).map(e => ({text: txt(e), vis: vis(e), cls: (typeof e.className === 'string' ? e.className : '').slice(0, 120)}));
  return {
    url: location.href,
    title: document.title,
    has_login_title: pick('.has-login-title'),
    quick_buttons: pick('button.fm-button.fm-submit'),
    password_input: pick('#fm-login-password'),
    account_input: pick('#fm-login-id'),
    checkcode_input: pick('#fm-login-checkcode'),
    agreement_checked: (document.querySelector('#fm-agreement-checkbox') || {}).checked,
    sms_tab: pick('.sms-login-tab-item'),
    qrcode_title: pick('.qrcode-title'),
    qrcode_canvas: pick('.qrcode-img canvas'),
    qrcode_error: pick('.qrcode-img .qrcode-error'),
    body_text: (document.body.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 400)
  };
}
"""


def redact(value: str) -> str:
    value = str(value or "")
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


def visible(items) -> bool:
    return any(i.get("vis") for i in items)


def cookie_map(page):
    out = {}
    for c in page.cookies(all_domains=True, all_info=True):
        name = c.get("name")
        if name in ("tracknick", "xlly_s", "_nk_", "cookie2"):
            out[name] = c
    return out


def quick_button(snap):
    for b in snap.get("quick_buttons", []):
        if b.get("vis") and "快速进入" in (b.get("text") or ""):
            return b
    return None


def judge(snap, nick_value):
    url = snap.get("url", "")
    if not any(h in url for h in LOGIN_HOSTS):
        return "logged_in", "auto"
    if "sec.taobao.com" in url:
        return "risk", "risk_page"
    if visible(snap.get("has_login_title", [])) and quick_button(snap):
        return "logged_in", "quick_enter_pending"
    if visible(snap.get("password_input", [])) or visible(snap.get("account_input", [])):
        return "not_login", "password_form"
    if visible(snap.get("qrcode_title", [])):
        return "not_login", "qr_only"
    return "unknown", "structure_error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="9223")
    ap.add_argument("--no-redirect", action="store_true")
    ap.add_argument("--click-quick-enter", action="store_true")
    ap.add_argument("--after-wait", type=float, default=8, help="点击快速进入后的等待秒数")
    ap.add_argument("--keep-tab", action="store_true")
    args = ap.parse_args()

    page = ChromiumPage(f"127.0.0.1:{args.port}")
    url = LOGIN_URL if args.no_redirect else f"{LOGIN_URL}?redirectURL=https%3A%2F%2Fwww.taobao.com%2F"

    tab = page.new_tab(url)
    tab.wait.load_start()
    time.sleep(3)

    snap = tab.run_js(SNAPSHOT_JS)
    cookies = cookie_map(tab)
    nick = cookies.get("tracknick", {}).get("value", "")
    state, branch = judge(snap, nick)

    result = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "open_url": url,
        "judge": {"state": state, "branch": branch},
        "tracknick_present_nonempty": bool(str(nick or "").strip()),
        "tracknick_redacted": redact(nick),
        "xlly_s": {
            "present": "xlly_s" in cookies,
            "value_redacted": redact(cookies.get("xlly_s", {}).get("value", "")),
            "expires": cookies.get("xlly_s", {}).get("expires"),
        },
        "page": snap,
    }

    if args.click_quick_enter and quick_button(snap):
        tab.run_js(
            "function(){const b=Array.from(document.querySelectorAll('button.fm-button.fm-submit'))"
            ".find(e=>e.vis!==false && (e.innerText||'').trim()==='快速进入');"
            "if(b){b.click();return true;}return false;}"
        )
        time.sleep(args.after_wait)
        after = tab.run_js(SNAPSHOT_JS)
        result["after_quick_enter"] = {
            "url": after.get("url"),
            "title": after.get("title"),
            "left_login_host": not any(h in (after.get("url") or "") for h in LOGIN_HOSTS),
            "body_text": after.get("body_text"),
        }
        result["tracknick_after"] = redact(cookie_map(tab).get("tracknick", {}).get("value", ""))

    out_dir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "page.html").write_text(tab.html, encoding="utf-8")

    print(json.dumps({
        "out": str(out_dir),
        "url": snap.get("url"),
        "judge": result["judge"],
        "tracknick_nonempty": result["tracknick_present_nonempty"],
        "quick_enter_button": bool(quick_button(snap)),
        "password_form_visible": visible(snap.get("password_input", [])),
        "qrcode_visible": visible(snap.get("qrcode_canvas", [])),
        "after_quick_enter": result.get("after_quick_enter", {}).get("url"),
    }, ensure_ascii=False, indent=2))

    if not args.keep_tab:
        try:
            tab.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
