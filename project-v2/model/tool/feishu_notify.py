# -*- coding: utf-8 -*-
"""飞书群通知：读 config/alert_local.json，签名后发送一条文本。

画布入口：main(text, title="登录告警")
Python 入口：send_text(text, title="", webhook=None, secret=None)
自测：python 工具箱/feishu_notify.py --dry-run | --test
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request

CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "alert_local.json")


def _cred():
    """取 alert_local.json 里的飞书地址/密钥；取不到返回空串。"""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            ch = json.load(f)["channels"]["feishu"]
        return ch.get("url") or "", ch.get("secret") or ""
    except Exception:
        return "", ""


def _sign(secret, timestamp):
    string_to_sign = "%s\n%s" % (timestamp, secret)
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_text(text, title="", webhook=None, secret=None):
    """发一条飞书文本。返回 {"status": ok|error|skipped, ...}。"""
    url, sec = (webhook, secret or "") if webhook else _cred()
    if not url:
        return {"status": "skipped", "error": "feishu webhook 未配置（alert_local.json）"}

    payload = {"msg_type": "text",
               "content": {"text": ("%s\n%s" % (title, text)) if title else text}}
    if sec:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(sec, ts)

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")[:300]
            try:
                j = json.loads(body)
                code = j.get("code", j.get("StatusCode", 0))
            except Exception:
                code = 0
            ok = r.status < 400 and code in (0, None)
            return {"status": "ok" if ok else "error", "http_status": r.status, "response": body}
    except Exception as e:
        return {"status": "error", "error": "%s: %s" % (type(e).__name__, e)}


def main(args=None):
    """影刀入口：args 可为 dict（text/title）或纯文本。"""
    if isinstance(args, dict):
        text = args.get("text") or ""
        title = args.get("title") or "登录告警"
    else:
        text = args or ""
        title = "登录告警"
    return send_text(text, title=title)


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        url, sec = _cred()
        print(json.dumps({"url_configured": bool(url), "secret_configured": bool(sec)}))
        sys.exit(0)
    if "--test" in sys.argv:
        res = send_text("RPA 飞书通知测试 %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
                        title="飞书通知测试")
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("status") == "ok" else 1)
    print("用法：python feishu_notify.py --dry-run | --test")
