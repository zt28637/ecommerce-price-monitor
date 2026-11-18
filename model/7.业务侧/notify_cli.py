# -*- coding: utf-8 -*-
"""影刀 / 命令行通知入口：复用 N5 的 notify.alert，不在画布重配飞书。

用法：
  python model/7.业务侧/notify_cli.py --status-file runtime/state/last_batch.txt
  python model/7.业务侧/notify_cli.py --text-file runtime/state/shadowbot_error.txt --title 影刀调用异常
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = os.path.dirname(_HERE)
for _p in (_HERE,
           os.path.join(_MODEL, "tool"),
           os.path.join(_MODEL, "5.价格告警")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def main(args=None):
    ap = argparse.ArgumentParser(description="复用 N5 notify.alert 发通知")
    ap.add_argument("--text", default="")
    ap.add_argument("--text-file", default="")
    ap.add_argument("--status-file", default="")
    ap.add_argument("--title", default="竞品监控流程异常")
    ap.add_argument("--dry-run", action="store_true", help="只校验通道，不发消息")
    a = vars(ap.parse_args(args))
    text = a["text"] or _read(a["text_file"]) or _read(a["status_file"])
    if not text:
        text = "竞品监控流程异常（无状态文本）"
    if a["dry_run"]:
        try:
            import alert_build
            cfg = alert_build.load()
            channels = cfg.get("channels") or {}
            name = channels.get("default") or "file"
            target = channels.get(name) or {}
            print(json.dumps({"ok": True, "channel": name,
                              "type": target.get("type"),
                              "has_url": bool(target.get("url")),
                              "text": text}, ensure_ascii=False))
            return 0
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
            return 1
    try:
        import notify
        res = notify.alert(text, a["title"])
        print(json.dumps(res, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
