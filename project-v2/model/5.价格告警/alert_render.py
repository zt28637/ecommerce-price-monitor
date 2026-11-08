"""告警渲染：Markdown 日报 + 即时推送文本。

同一份告警数据，两种输出：
  · 文件：完整 Markdown（即时 + 日报 + 新品 + 口径说明）
  · 推送：只含即时条目，长度可控，钉钉/飞书都能直接显示
"""

TYPE_CN = {"price_drop": "降价", "price_rise": "涨价", "new_top": "新品进头部"}
LEVEL_CN = {"instant": "即时", "daily": "日报"}


def _money(v):
    return "-" if v is None else "%.2f" % float(v)


def _one(a, bullet="- "):
    head = "%s **%s**（%s）" % (
        "⬇" if a["type"] == "price_drop" else ("⬆" if a["type"] == "price_rise" else "★"),
        (a.get("title") or a["product_id"])[:50], a["product_id"])
    lines = [head]
    if a.get("change_pct") is not None:
        lines.append("  - 上次 %s → 现价 %s（%+.2f%%）" % (
            _money(a["last_price"]), _money(a["current_price"]), a["change_pct"]))
    else:
        lines.append("  - 现价 %s" % _money(a["current_price"]))
    extra = []
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
                  s["by_type"]["price_drop"], s["by_type"]["price_rise"],
                  s["by_type"]["new_top"]))
    out.append("> 数据源：detail %d / list %d ｜ 历史 %d 天 ｜ 大促：%s"
               % (s["sources"].get("detail", 0), s["sources"].get("list", 0),
                  s.get("history_days", 0), s.get("promo") or "无"))
    if s.get("promo_downgraded"):
        out.append("> 大促期即时降级：%d 条" % s["promo_downgraded"])
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
            "- 5–10% 进日报；>10% 或历史新低即时推；大促期即时降为日报，避免误报。",
            "- 涨价/降价只在同一价格源内比较（detail 对 detail、list 对 list），"
            "避免列表价与详情价口径不同造成假信号。",
            "- 趋势价优先 detail；列表价只作触发器。",
            "- 入库只消费 auto_pass / approved；pending 复核前不参与。"]
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
        if a.get("change_pct") is not None:
            line += "：%s → %s（%+.2f%%）" % (
                _money(a["last_price"]), _money(a["current_price"]), a["change_pct"])
        if a.get("consecutive_down_days"):
            line += "，连跌 %d 天" % a["consecutive_down_days"]
        if a.get("is_new_low"):
            line += "，历史新低"
        line += " ｜ %s" % a.get("suggestion", "观察")
        lines.append("- " + line)
    if len(instant) > max_items:
        lines.append("- ……另有 %d 条，见日报" % (len(instant) - max_items))
    return "\n".join(lines)
