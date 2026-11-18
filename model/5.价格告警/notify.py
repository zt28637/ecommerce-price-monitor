"""推送通道：可替换配置，默认不发送。

支持三种 type：
  file      只落盘（默认，不联网）
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
    print(json.dumps(build_payload("feishu", "t", "hello"), ensure_ascii=False))


def alert(text, title="流程告警"):
    """运维告警：按 alert.json 默认通道发送一条文本（画布 Catch 用）。

    与业务告警共用同一套通道配置；未配置 webhook 时返回 error/skipped，不抛错。
    """
    import alert_build
    cfg = alert_build.load()
    return deliver_all(cfg, title, text, [], enabled=True)


TYPE_CN = {"price_drop": "降价", "price_rise": "涨价", "new_top": "新品进头部"}
LEVEL_CN = {"instant": "即时", "daily": "日报"}
ICON = {"price_drop": "⬇", "price_rise": "⬆", "new_top": "★"}


def _money(v):
    return "-" if v is None else "%.2f" % float(v)


def _one(a, bullet="- "):
    head = "%s **%s**（%s）" % (
        ICON.get(a["type"], "•"),
        (a.get("title") or a["product_id"])[:50], a["product_id"])
    lines = [head]
    if a.get("change_pct") is not None:
        lines.append("  - 上次 %s → 现价 %s（%+.2f%%）" % (
            _money(a["last_price"]), _money(a["current_price"]), a["change_pct"]))
    else:
        lines.append("  - 现价 %s" % _money(a["current_price"]))
    extra = []
    if a.get("change_abs") not in (None, 0):
        extra.append("差额 %+.2f 元" % a["change_abs"])
    if a.get("consecutive_down_days"):
        extra.append("连续下跌 %d 天" % a["consecutive_down_days"])
    if a.get("affected_sku_count"):
        extra.append("影响 SKU %d 个" % a["affected_sku_count"])
    if a.get("total_sku_count") and a.get("affected_sku_count"):
        extra[-1] += " / 共 %d 个" % a["total_sku_count"]
    if a.get("is_new_low"):
        extra.append("历史新低")
    extra.append("价格源 %s" % (a.get("price_source") or "-"))
    if a.get("shop_name"):
        extra.append("店铺 %s" % a["shop_name"])
    lines.append("  - " + " ｜ ".join(extra))
    lines.append("  - 建议：%s" % a.get("suggestion", "观察"))
    if a.get("note"):
        lines.append("  - 备注：%s" % a["note"])
    return "\n".join([bullet.rstrip() + " " + lines[0]] + lines[1:])


def render_markdown(date, alerts, summary):
    s = summary or {}
    out = ["# 竞品价格告警 · %s" % date, ""]
    out.append("> 共 **%d** 条：即时 **%d** / 日报 **%d** ｜ 降价 %d · 涨价 %d · 新品 %d"
               % (s.get("total", 0), s.get("instant", 0), s.get("daily", 0),
                  s["by_type"].get("price_drop", 0), s["by_type"].get("price_rise", 0),
                  s["by_type"].get("new_top", 0)))
    out.append("> 数据源：detail %d / list %d ｜ 历史 %d 天"
               % (s["sources"].get("detail", 0), s["sources"].get("list", 0),
                  s.get("history_days", 0)))
    out.append("")

    for level in ("instant", "daily"):
        group = [a for a in alerts if a["level"] == level]
        if not group:
            continue
        out.append("## %s（%d）" % (LEVEL_CN[level], len(group)))
        out.append("")
        for a in group:
            out.append(_one(a))
            out.append("")

    for note in (s.get("notes") or []):
        out.append("> %s" % note)
    if s.get("notes"):
        out.append("")

    out += ["## 口径", "",
            "- 涨跌幅或绝对差额任一达到阈值即告警；即时/日报按配置。",
            "- 历史新低即时；列表价只进日报。",
            "- 涨价/降价只在同一价格源内比较（detail 对 detail、list 对 list），"
            "避免列表价与详情价口径不同造成假信号。",
            "- 趋势价优先 detail；列表价只作触发器。",
            "- 入库只消费 auto_pass / approved；pending 复核前不参与。",
            "- 同一 alert_id 在冷却期内不重复推；继续同向波动 ≥ 再报阈值才再推。"]
    return "\n".join(out).rstrip() + "\n"


def render_push(alerts, summary, max_items=10):
    """即时推送文本（只含 instant）。没有即时告警返回 ''。"""
    instant = [a for a in alerts if a["level"] == "instant"]
    if not instant:
        return ""
    lines = ["竞品价格告警 · %s · 即时 %d 条" % (summary.get("date"), len(instant)), ""]
    for a in instant[:max_items]:
        line = "%s %s" % (TYPE_CN.get(a["type"], a["type"]),
                          (a.get("title") or a["product_id"])[:36])
        if a.get("last_price") is not None:
            line += "：%s → %s" % (_money(a["last_price"]),
                                   _money(a["current_price"]))
            if a.get("change_pct") not in (None, 0):
                line += "（%+.2f%%）" % a["change_pct"]
        elif a.get("current_price") is not None:
            line += "：现价 %s" % _money(a["current_price"])
        if a.get("consecutive_down_days"):
            line += "，连跌 %d 天" % a["consecutive_down_days"]
        if a.get("is_new_low"):
            line += "，历史新低"
        line += " ｜ %s" % a.get("suggestion", "观察")
        lines.append("- " + line)
    if len(instant) > max_items:
        lines.append("- ……另有 %d 条，见日报" % (len(instant) - max_items))
    return "\n".join(lines)



def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
