"""推送通道：可替换配置，默认不发送。

支持四种 type：
  file      只落盘（默认，不联网）
  dingtalk  钉钉机器人 markdown（可选加签 secret）
  feishu    飞书机器人 text（签名/重试统一走 工具箱/feishu_notify.py）
  webhook   通用 JSON POST（自建接口直接换这里）

约定：
  · 只有显式 --send 才调用 send()；run_alert 默认只生成文件
  · webhook/secret 只从 alert_local.json 或环境变量取，日志不打印 URL
  · 返回值统一 {"status": "ok|error|skipped", "channel": ..., ...}
"""

import json
import os
import sys
import time

try:
    import requests
except ImportError:      # 离线环境仍可生成文件
    requests = None

# 影刀 process.invoke_module 不会把模块目录放进 sys.path；补上才能导入同目录 CodeFlow
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

# 工具箱：仓库里是 model/tool；影刀应用内是 xbot_robot 同目录（已由 _MODULE_DIR 覆盖）
_TOOLBOX_CANDIDATES = [
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "tool")),
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "工具箱")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\model\tool",
]
for _p in _TOOLBOX_CANDIDATES:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
try:
    import feishu_notify
except ImportError:
    feishu_notify = None
try:
    import dingtalk_notify
except ImportError:
    dingtalk_notify = None

TIMEOUT = 10


def _post(url, payload, timeout=TIMEOUT):
    if requests is None:
        return {"status": "error", "error": "requests 未安装"}
    r = requests.post(url, json=payload, timeout=timeout,
                      headers={"Content-Type": "application/json"})
    body = (r.text or "")[:300]
    return {"status": "ok" if r.status_code < 400 else "error",
            "http_status": r.status_code, "response": body}


def build_payload(channel_type, title, text, alerts=None):
    if channel_type == "dingtalk":
        return {"msgtype": "markdown",
                "markdown": {"title": title, "text": text}}
    if channel_type == "feishu":
        return {"msg_type": "text", "content": {"text": "%s\n\n%s" % (title, text)}}
    # 通用 webhook：自建服务按这个结构取
    return {"title": title, "text": text, "alerts": alerts or []}


def send(channel_cfg, title, text, alerts=None, enabled=False):
    """发送一条消息。enabled=False 时直接 skipped，绝不联网。"""
    ch = dict(channel_cfg or {})
    typ = ch.get("type") or "file"
    name = ch.get("name") or typ
    if typ == "file":
        return {"status": "skipped", "channel": name, "reason": "file 通道不联网"}
    if not enabled:
        return {"status": "skipped", "channel": name, "reason": "未传 --send"}
    if typ == "feishu":
        if feishu_notify is None:
            return {"status": "error", "channel": name, "error": "feishu_notify 未找到"}
        res = feishu_notify.send_text(text, title=title,
                                       webhook=ch.get("url") or None,
                                       secret=ch.get("secret") or None)
        res["channel"] = name
        return res
    if typ == "dingtalk":
        if dingtalk_notify is None:
            return {"status": "error", "channel": name, "error": "dingtalk_notify 未找到"}
        res = dingtalk_notify.send_text(text, title=title,
                                         webhook=ch.get("url") or None,
                                         secret=ch.get("secret") or None,
                                         keyword=ch.get("keyword") or None)
        res["channel"] = name
        return res
    url = ch.get("url") or ""
    if not url:
        return {"status": "skipped", "channel": name,
                "reason": "webhook 未配置（alert_local.json 或环境变量）"}
    payload = build_payload(typ, title, text, alerts)
    res = _post(url, payload)
    res["channel"] = name
    return res


def deliver_all(cfg, title, text, alerts, enabled=False, only=None):
    """按配置发送。only 指定单个通道名（可选）。返回结果列表。"""
    channels = cfg.get("channels") or {}
    names = [only] if only else [channels.get("default") or "file"]
    out = []
    for name in names:
        ch = dict(channels.get(name) or {"type": "file"})
        ch.setdefault("name", name)
        out.append(send(ch, title, text, alerts, enabled=enabled))
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build_payload("dingtalk", "t", "hello"), ensure_ascii=False))
    print(json.dumps(build_payload("feishu", "t", "hello"), ensure_ascii=False))


def alert(text, title="流程告警"):
    """运维告警：按 alert.json 默认通道发送一条文本（画布 Catch 用）。

    与业务告警共用同一套通道配置；未配置 webhook 时返回 error/skipped，不抛错。
    """
    import alert_config
    cfg = alert_config.load()
    return deliver_all(cfg, title, text, [], enabled=True)


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
