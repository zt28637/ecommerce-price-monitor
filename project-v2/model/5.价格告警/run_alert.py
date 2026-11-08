"""告警总入口：读事实表 -> 生成告警 -> 落盘 ->（可选）推送。

用法：
  # 只生成，不发（默认）
  python run_alert.py --date 2026-11-01

  # 指定测试库
  python run_alert.py --date 2026-11-01 --database price_monitor_v2_test

  # 真正推送（需在 alert_local.json 或环境变量里配好 webhook）
  python run_alert.py --date 2026-11-01 --send
  python run_alert.py --date 2026-11-01 --send --send-daily --channel feishu

目录：runtime/v2/alerts/<YYYYMMDD>/
  alerts.jsonl        告警明细（机器读）
  告警_<date>.md       人在看的日报（即时 + 日报 + 新品 + 口径）
  summary.json        计数与诊断
  push_log.jsonl      推送结果与已发 alert_id（重跑不重复推）
"""

import argparse
import datetime
import json
import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

_INGEST_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "4.数据入库"))
if _INGEST_DIR not in sys.path:
    sys.path.insert(0, _INGEST_DIR)

import alert_build
import alert_config
import alert_render
import db
import notify

# _MODULE_DIR 是 project-v2/model/5.价格告警，退两层才到 project-v2/
PROJECT_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))
DEFAULT_OUT_ROOT = os.path.join(PROJECT_DIR, "runtime", "alerts")


def _log(msg):
    print(msg)
    sys.stdout.flush()


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(part, path)


def _load_sent(path):
    sent = set()
    if not os.path.exists(path):
        return sent
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "ok":
                sent.update(r.get("alert_ids") or [])
    return sent


def run(args):
    cfg = alert_config.load(args.get("alert_config"))
    periods = alert_config.promo_periods()

    conn = db.connect(args.get("config"), args.get("database"))
    try:
        cur = conn.cursor()
        date = args.get("date") or alert_build.latest_date(cur)
        if not date:
            raise SystemExit("事实表里没有数据，先跑 run_ingest.py")
        promo = alert_config.promo_of(date, periods)

        built = alert_build.build(cur, date, cfg, promo=promo)
        alerts = built["alerts"]
        summary = built["summary"]
    finally:
        conn.close()

    out_dir = args.get("out")
    if not out_dir:
        file_dir = ((cfg.get("channels") or {}).get("file") or {}).get("dir") or ""
        if file_dir and not os.path.isabs(file_dir):
            file_dir = os.path.join(PROJECT_DIR, file_dir)
        out_dir = os.path.join(file_dir or DEFAULT_OUT_ROOT, date.replace("-", ""))
    os.makedirs(out_dir, exist_ok=True)
    md = alert_render.render_markdown(date, alerts, summary)
    push_text = alert_render.render_push(alerts, summary)

    _write_jsonl(os.path.join(out_dir, "alerts.jsonl"), alerts)
    _write_text(os.path.join(out_dir, "告警_%s.md" % date), md)
    _write_text(os.path.join(out_dir, "summary.json"),
                json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    _log("[告警] %s | 共 %d（即时 %d / 日报 %d）| 降价 %d 涨价 %d 新品 %d" % (
        date, summary["total"], summary["instant"], summary["daily"],
        summary["by_type"]["price_drop"], summary["by_type"]["price_rise"],
        summary["by_type"]["new_top"]))
    _log("[告警] 数据源 detail %(detail)d / list %(list)d | 历史 %(history_days)d 天"
         " | 大促 %(promo)s" % {"detail": summary["sources"]["detail"],
                               "list": summary["sources"]["list"],
                               "history_days": summary["history_days"],
                               "promo": summary["promo"] or "无"})
    for note in summary.get("notes") or []:
        _log("[告警] 注：%s" % note)
    _log("[告警] 产物：%s" % out_dir)

    if args.get("preview"):
        print("\n" + md)

    push_log = os.path.join(out_dir, "push_log.jsonl")
    results = []
    if args.get("send"):
        sent = _load_sent(push_log)
        instant = [a for a in alerts if a["level"] == "instant"
                   and a["alert_id"] not in sent]
        channel = args.get("channel") or ""
        if instant and cfg.get("send_instant", True):
            title = "竞品价格告警 · %s" % date
            text = alert_render.render_push(instant, summary)
            res = notify.deliver_all(cfg, title, text, instant,
                                     enabled=True, only=channel or None)
            for r in res:
                r.update({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                          "date": date, "level": "instant",
                          "alert_ids": [a["alert_id"] for a in instant]})
            results += res
            _append_log(push_log, res)
            _log("[告警] 即时推送：%s" % _brief(res))
        else:
            reason = "无新即时告警" if not instant else "配置关闭即时推送"
            _log("[告警] 即时推送跳过：%s" % reason)

        if args.get("send_daily") or cfg.get("send_daily"):
            title = "竞品价格日报 · %s" % date
            res = notify.deliver_all(cfg, title, md, alerts,
                                     enabled=True, only=channel or None)
            for r in res:
                r.update({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                          "date": date, "level": "daily",
                          "alert_ids": [a["alert_id"] for a in alerts]})
            results += res
            _append_log(push_log, res)
            _log("[告警] 日报推送：%s" % _brief(res))
    else:
        _log("[告警] 未推送（默认只生成；加 --send 才发）")

    return {"date": date, "out_dir": out_dir, "summary": summary,
            "push": results, "alerts": len(alerts)}


def _brief(results):
    return " / ".join("%s:%s%s" % (
        r.get("channel"), r.get("status"),
        ("(" + str(r.get("http_status")) + ")") if r.get("http_status") else
        ("(" + str(r.get("reason") or r.get("error") or "") + ")" if r.get("status") != "ok" else ""))
        for r in results)


def _append_log(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def main(args=None):
    return run(args or {})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v2 价格告警")
    ap.add_argument("--date", default="", help="告警日期；默认事实表最新一天")
    ap.add_argument("--database", default="", help="覆盖库名（测试库用）")
    ap.add_argument("--config", default="", help="database.json 路径")
    ap.add_argument("--alert-config", default="", help="alert.json 路径")
    ap.add_argument("--out", default="", help="输出目录；默认 runtime/v2/alerts/<YYYYMMDD>")
    ap.add_argument("--send", action="store_true", help="真正调用推送通道")
    ap.add_argument("--send-daily", action="store_true", help="连日报一起推")
    ap.add_argument("--channel", default="", help="指定通道名（dingtalk/feishu/custom/file）")
    ap.add_argument("--preview", action="store_true", help="把 Markdown 打到终端")
    run(vars(ap.parse_args()))
