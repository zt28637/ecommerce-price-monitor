# -*- coding: utf-8 -*-
"""钉钉群通知：读 config/alert_local.json 的 channels.dingtalk，加签后发送 markdown。

画布入口：main(text, title="登录告警")
Python 入口：send_text(text, title="", webhook=None, secret=None)
环境变量兜底：DINGTALK_WEBHOOK / DINGTALK_SECRET
自测：python 工具箱/dingtalk_notify.py --dry-run | --test
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
# 影刀把 CodeFlow 复制到 xbot_robot 下执行，相对路径会指到应用目录；
# 因此与列表层同款：环境变量 > 相对仓库 > 本机绝对路径。
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2",
]


def _first_project(candidates):
    for p in candidates:
        if p and os.path.isdir(os.path.join(p, "model")):
            return p
    return os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))


CONFIG = os.path.join(_first_project(_PROJECT_CANDIDATES),
                      "config", "alert_local.json")


def _resolve(value):
    """`${ENV}` / `env:ENV` -> 环境变量；解析不到返回空串。"""
    if not isinstance(value, str):
        return value
    s = value.strip()
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", s) or \
        re.fullmatch(r"env:([A-Za-z_][A-Za-z0-9_]*)", s)
    return os.environ.get(m.group(1), "") if m else value


def _cred():
    """取 alert_local.json 的 channels.dingtalk；缺省回落到环境变量。"""
    url = secret = keyword = ""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            ch = json.load(f).get("channels", {}).get("dingtalk", {})
        url = _resolve(ch.get("url") or "") or ""
        secret = _resolve(ch.get("secret") or "") or ""
        keyword = _resolve(ch.get("keyword") or "") or ""
    except Exception:
        pass
    return (url or os.environ.get("DINGTALK_WEBHOOK", ""),
            secret or os.environ.get("DINGTALK_SECRET", ""),
            keyword or os.environ.get("DINGTALK_KEYWORD", ""))


def _signed_url(url, secret):
    if not secret:
        return url
    ts = str(round(time.time() * 1000))
    raw = "%s\n%s" % (ts, secret)
    code = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"),
                    hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(code))
    sep = "&" if "?" in url else "?"
    return "%s%stimestamp=%s&sign=%s" % (url, sep, ts, sign)


def send_text(text, title="", webhook=None, secret=None, keyword=None):
    """发一条钉钉 markdown。返回 {"status": ok|error|skipped, ...}。"""
    if webhook:
        url, sec, kw = webhook, secret or "", keyword or ""
    else:
        url, sec, kw = _cred()
        kw = keyword if keyword is not None else kw
    if not url:
        return {"status": "skipped",
                "error": "dingtalk webhook 未配置（alert_local.json / DINGTALK_WEBHOOK）"}

    # 关键词模式：消息必须命中机器人关键词，否则钉钉返回 310000
    if kw and kw not in text:
        text = "%s\n%s" % (kw, text)

    title = title or "RPA 通知"
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    req = urllib.request.Request(
        _signed_url(url, sec),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")[:300]
            try:
                code = json.loads(body).get("errcode", 0)
            except Exception:
                code = 0
            ok = r.status < 400 and code in (0, None)
            return {"status": "ok" if ok else "error",
                    "http_status": r.status, "response": body}
    except Exception as e:
        return {"status": "error", "error": "%s: %s" % (type(e).__name__, e)}


def main(text, title="登录告警"):
    """影刀「调用模块」入口。"""
    return send_text(text, title=title)


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        url, sec, kw = _cred()
        print(json.dumps({"url_configured": bool(url),
                          "secret_configured": bool(sec),
                          "keyword_configured": bool(kw)}))
        sys.exit(0)
    if "--test" in sys.argv:
        res = send_text("RPA 钉钉通知测试 %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
                        title="钉钉通知测试")
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("status") == "ok" else 1)
    print("用法：python dingtalk_notify.py --dry-run | --test")
