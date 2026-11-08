"""从事实表生成告警（纯逻辑 + 只读查询）。

三类（plan §6.1）：
  price_drop  竞品降价 -> 我要不要跟
  price_rise  竞品涨价 -> 我能不能提
  new_top     新品进头部 -> 格局变了

口径：
  · 只读 review_status ∈ {auto_pass, approved} 的事实
  · 比价必须同源：detail 对 detail、list 对 list，避免"列表价 vs 详情价"假跌
  · 趋势价优先 detail；SKU 明细可用时，用 SKU 告警替代列表价告警
  · 5–10% 进日报；>10% 或创新低即时推（大促期间即时降为日报）
  · 所有判断基于「上一次有效价」，断跑不丢信号
"""

import datetime
from collections import defaultdict

OK_STATUS = ("auto_pass", "approved")


# ------------------------------------------------------------
# 查询
# ------------------------------------------------------------
def latest_date(cur):
    cur.execute("SELECT MAX(crawl_date) FROM fact_item_price")
    d = cur.fetchone()[0]
    if d:
        return str(d)
    cur.execute("SELECT MAX(crawl_date) FROM fact_sku_price")
    d = cur.fetchone()[0]
    return str(d) if d else ""


def load_item_history(cur, date):
    cur.execute("""
        SELECT product_id, crawl_date, price, price_list, price_source, sales
        FROM fact_item_price
        WHERE crawl_date <= %s
          AND review_status IN ('auto_pass', 'approved')
          AND price IS NOT NULL
          AND price_source IN ('detail', 'list')
          -- 部分 SKU 缺价的详情价不可比：它会在"有价子集最低价"之间跳动，
          -- 直接被当成降价。列表价是触发器，本身就没有完整价概念，不设此限。
          AND (price_source = 'list' OR price_complete = 1)
        ORDER BY product_id, crawl_date
    """, (date,))
    return list(cur.fetchall())


def load_dims(cur):
    cur.execute("""
        SELECT product_id, title, shop_name, first_seen_date
        FROM dim_product WHERE is_current = 1
    """)
    return {r[0]: {"title": r[1], "shop_name": r[2], "first_seen": str(r[3])}
            for r in cur.fetchall()}


def load_sku_changes(cur, date):
    cur.execute("""
        SELECT sku_id, product_id, price, prev_price, change_pct,
               down_streak, min_before
        FROM v2_sku_change
        WHERE crawl_date = %s
    """, (date,))
    return list(cur.fetchall())


def load_sku_counts(cur):
    cur.execute("SELECT product_id, COUNT(*) FROM dim_sku GROUP BY product_id")
    return {r[0]: r[1] for r in cur.fetchall()}


def history_days(cur, date):
    cur.execute("SELECT COUNT(DISTINCT crawl_date) FROM fact_item_price WHERE crawl_date < %s",
                (date,))
    return int(cur.fetchone()[0] or 0)


# ------------------------------------------------------------
# 规则
# ------------------------------------------------------------
def _down_streak(prices):
    """prices 升序；末尾连续下跌天数。"""
    n = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] < prices[i - 1]:
            n += 1
        else:
            break
    return n


def _suggest(kind, level, new_low):
    if kind == "drop":
        if new_low:
            return "跟价（历史新低，先算毛利）"
        return "跟价（先算毛利）" if level == "instant" else "观察，连续下跌再跟"
    if kind == "rise":
        return "可评估提价" if level == "instant" else "观察"
    return "观察"


def _pct(cur, prev):
    return round((cur - prev) / prev * 100.0, 2) if prev else None


def _alert_id(*parts):
    import hashlib
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _base_alert(date, kind, entity, pid, title, shop):
    return {
        "alert_id": "", "date": date,
        "type": {"drop": "price_drop", "rise": "price_rise"}.get(kind, kind),
        "entity": entity,
        "level": "daily", "product_id": pid, "sku_id": "",
        "title": title or "", "shop_name": shop or "",
        "last_price": None, "current_price": None, "change_pct": None,
        "consecutive_down_days": 0, "affected_sku_count": 0,
        "price_source": "", "is_new_low": False,
        "suggestion": _suggest(kind, "daily", False),
        "promo": None, "note": "",
    }


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def build(cur, date, cfg, promo=None):
    th = cfg["thresholds"]
    dims = load_dims(cur)
    sku_counts = load_sku_counts(cur)
    rows = load_item_history(cur, date)

    # pid -> [(date, price, source)]
    hist = defaultdict(list)
    for pid, day, price, _pl, source, _sales in rows:
        hist[pid].append((str(day), float(price), source))

    target = [r for r in rows if str(r[1]) == date]
    item_alerts = {}
    notes = []
    sources = {"detail": 0, "list": 0}

    for pid, day, price, price_list, source, sales in target:
        sources[source] = sources.get(source, 0) + 1
        cur_price = float(price)
        prior = [p for (d, p, s) in hist[pid] if d < date and s == source]
        if not prior:
            continue
        prev = prior[-1]
        pct = _pct(cur_price, prev)
        if pct is None:
            continue
        kind = "drop" if pct < 0 else "rise"
        if kind == "drop":
            daily, instant = th["drop_pct_daily"], th["drop_pct_instant"]
        else:
            daily, instant = th["rise_pct_daily"], th["rise_pct_instant"]
        if abs(pct) < daily:
            continue

        new_low = kind == "drop" and cur_price < min(prior)
        level = "instant" if (abs(pct) >= instant or
                              (new_low and th.get("new_low_instant", True))) else "daily"
        note = ""
        if source == "list":
            # 列表价只是触发器：没有详情价确认时最多进日报，避免把活动价当真实降价
            if level == "instant":
                note = "列表价信号，未经详情确认，已降为日报"
            level = "daily"
        info = dims.get(pid, {})
        a = _base_alert(date, kind, "item", pid,
                        info.get("title"), info.get("shop_name"))
        a.update({
            "level": level,
            "last_price": round(prev, 2),
            "current_price": round(cur_price, 2),
            "change_pct": pct,
            "consecutive_down_days": _down_streak(prior + [cur_price]) if kind == "drop" else 0,
            "price_source": source,
            "is_new_low": new_low,
            "suggestion": _suggest(kind, level, new_low),
            "promo": promo,
            "affected_sku_count": 0,
            "note": note,
        })
        item_alerts[pid] = a

    # SKU 明细：补充影响 SKU 数；没有详情价告警时用 SKU 告警替代列表价告警
    sku_alerts = []
    sku_rows = load_sku_changes(cur, date)
    sku_by_pid = defaultdict(list)
    for r in sku_rows:
        sku_id, pid, price, prev, pct, streak, min_before = r
        if pct is None or prev is None:
            continue
        kind = "drop" if pct < 0 else "rise"
        limit = th["drop_pct_daily"] if kind == "drop" else th["rise_pct_daily"]
        if abs(float(pct)) < limit:
            continue
        sku_by_pid[pid].append(r)

    for pid, moves in sku_by_pid.items():
        affected = len(moves)
        existing = item_alerts.get(pid)
        if existing:
            existing["affected_sku_count"] = max(affected, 1)

        # 取波动最大的一条 SKU 作代表
        rep = max(moves, key=lambda r: abs(float(r[4])))
        sku_id, _, price, prev, pct, streak, min_before = rep
        price, prev, pct = float(price), float(prev), float(pct)
        kind = "drop" if pct < 0 else "rise"
        new_low = kind == "drop" and min_before is not None and price < float(min_before)
        daily, instant = ((th["drop_pct_daily"], th["drop_pct_instant"]) if kind == "drop"
                          else (th["rise_pct_daily"], th["rise_pct_instant"]))
        level = "instant" if (abs(pct) >= instant or
                              (new_low and th.get("new_low_instant", True))) else "daily"
        # 去重只在"不会漏掉更急的信号"时成立：
        #   · 已有列表价告警 → 用 SKU 明细替代（原设计）
        #   · 已有商品级告警且已是 instant → 不必再报
        #   · 已有商品级 daily、但某个 SKU 到了 instant（如商品跌 5%、某 SKU 跌 30%）
        #     → 必须单独报，否则即时推送被日报吞掉
        note = ""
        if existing:
            if existing["price_source"] == "list":
                item_alerts.pop(pid, None)      # 列表价信号由 SKU 明细替代，不重复报
                note = "由列表价信号升级为 SKU 明细告警"
            elif existing["level"] == "instant" or level != "instant":
                continue
            else:
                note = "商品级仅进日报，该 SKU 波动更大，单独即时告警"
        info = dims.get(pid, {})
        a = _base_alert(date, kind, "sku", pid, info.get("title"), info.get("shop_name"))
        a.update({
            "level": level, "sku_id": sku_id,
            "last_price": round(prev, 2), "current_price": round(price, 2),
            "change_pct": round(pct, 2),
            "consecutive_down_days": int(streak or 0),
            "affected_sku_count": affected,
            "price_source": "detail", "is_new_low": new_low,
            "suggestion": _suggest(kind, level, new_low),
            "promo": promo,
            "note": note,
        })
        sku_alerts.append(a)

    # 新品进头部
    new_alerts = []
    np_cfg = cfg.get("new_product") or {}
    days_hist = history_days(cur, date)
    if np_cfg.get("enabled", True):
        if days_hist < int(np_cfg.get("min_history_days", 3)):
            notes.append("新品进头部：历史仅 %d 天，未达 %d 天，本次跳过"
                         % (days_hist, int(np_cfg.get("min_history_days", 3))))
        else:
            cutoff = (datetime.date.fromisoformat(date)
                      - datetime.timedelta(days=int(np_cfg.get("days", 7)))).isoformat()
            ranked = sorted([r for r in target if r[5] is not None],
                            key=lambda r: int(r[5]), reverse=True)[:int(np_cfg.get("top_n", 10))]
            for pid, day, price, price_list, source, sales in ranked:
                info = dims.get(pid, {})
                if not info.get("first_seen") or info["first_seen"] < cutoff:
                    continue
                a = _base_alert(date, "new_top", "item", pid,
                                info.get("title"), info.get("shop_name"))
                a.update({
                    "level": "daily", "current_price": round(float(price), 2),
                    "price_source": source, "sales": int(sales),
                    "suggestion": "观察（新品进头部）",
                    "promo": promo,
                    "note": "首次出现 %s，销量 %s，进入当日前 %d"
                            % (info["first_seen"], sales, int(np_cfg.get("top_n", 10))),
                })
                new_alerts.append(a)

    alerts = list(item_alerts.values()) + sku_alerts + new_alerts

    # 大促降级
    suppressed = 0
    if promo and (cfg.get("promo") or {}).get("downgrade_instant", True):
        for a in alerts:
            if a["level"] == "instant":
                a["level"] = "daily"
                a["note"] = (a["note"] + "；" if a["note"] else "") + \
                    "大促期（%s）即时降为日报" % promo
                suppressed += 1

    for a in alerts:
        a["alert_id"] = _alert_id(date, a["type"], a["entity"], a["product_id"],
                                  a["sku_id"], a["change_pct"], a["level"])
        a["total_sku_count"] = sku_counts.get(a["product_id"], 0)

    alerts.sort(key=lambda x: (0 if x["level"] == "instant" else 1,
                               x["type"], x.get("change_pct") or 0))

    summary = {
        "date": date,
        "total": len(alerts),
        "instant": sum(1 for a in alerts if a["level"] == "instant"),
        "daily": sum(1 for a in alerts if a["level"] == "daily"),
        "by_type": {t: sum(1 for a in alerts if a["type"] == t)
                    for t in ("price_drop", "price_rise", "new_top")},
        "sources": sources,
        "history_days": days_hist,
        "promo": promo,
        "promo_downgraded": suppressed,
        "notes": notes,
    }
    return {"alerts": alerts, "summary": summary}
