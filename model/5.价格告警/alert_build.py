"""从事实表生成告警（纯逻辑 + 只读查询）。

三类（plan §6.1）：
  price_drop  竞品降价 -> 我要不要跟
  price_rise  竞品涨价 -> 我能不能提
  new_top     新品进头部 -> 格局变了

口径：
  · 只读 review_status ∈ {auto_pass, approved} 的事实
  · 比价必须同源：detail 对 detail、list 对 list，避免"列表价 vs 详情价"假跌
  · 趋势价优先 detail；SKU 明细可用时，用 SKU 告警替代列表价告警
  · 5–10% 进日报；>10% 或创新低即时推
  · 所有判断基于「上一次有效价」，断跑不丢信号
"""

import datetime
import json
import os
import re
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
        "change_abs": None,
        "consecutive_down_days": 0, "affected_sku_count": 0,
        "price_source": "", "is_new_low": False,
        "suggestion": _suggest(kind, "daily", False),
        "note": "",
    }


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def build(cur, date, cfg):
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
        prev = prior[-1] if prior else None
        pct = _pct(cur_price, prev) if prev is not None else None
        abs_diff = round(cur_price - prev, 2) if prev is not None else None

        kind = None
        level = None
        new_low = False
        if pct is not None and pct != 0:
            kind = "drop" if pct < 0 else "rise"
            daily = th["drop_pct_daily"] if kind == "drop" else th["rise_pct_daily"]
            instant = th["drop_pct_instant"] if kind == "drop" else th["rise_pct_instant"]
            abs_daily = th.get("%s_abs_daily" % kind, 0) or 0
            abs_instant = th.get("%s_abs_instant" % kind, 0) or 0
            abs_move = abs(abs_diff or 0)
            if abs(pct) >= daily or (abs_daily > 0 and abs_move >= abs_daily):
                new_low = kind == "drop" and cur_price < min(prior)
                level = "instant" if (
                    abs(pct) >= instant
                    or (abs_instant > 0 and abs_move >= abs_instant)
                    or (new_low and th.get("new_low_instant", True))
                ) else "daily"

        if kind is None or level is None:
            continue

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
            "change_abs": abs_diff,
            "consecutive_down_days": _down_streak(prior + [cur_price]) if kind == "drop" else 0,
            "price_source": source,
            "is_new_low": new_low,
            "suggestion": _suggest(kind, level, new_low),
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
        abs_limit = th.get("%s_abs_daily" % kind, 0) or 0
        abs_move = abs(round(float(price) - float(prev), 2))
        if abs(float(pct)) < limit and not (abs_limit > 0 and abs_move >= abs_limit):
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
        abs_daily = th.get("%s_abs_daily" % kind, 0) or 0
        abs_instant = th.get("%s_abs_instant" % kind, 0) or 0
        abs_move = abs(round(price - prev, 2))
        if abs(pct) < daily and not (abs_daily > 0 and abs_move >= abs_daily):
            continue
        level = "instant" if (
            abs(pct) >= instant
            or (abs_instant > 0 and abs_move >= abs_instant)
            or (new_low and th.get("new_low_instant", True))
        ) else "daily"
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
            "change_abs": round(price - prev, 2),
            "consecutive_down_days": int(streak or 0),
            "affected_sku_count": affected,
            "price_source": "detail", "is_new_low": new_low,
            "suggestion": _suggest(kind, level, new_low),
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
                            "note": "首次出现 %s，销量 %s，进入当日前 %d"
                            % (info["first_seen"], sales, int(np_cfg.get("top_n", 10))),
                })
                new_alerts.append(a)

    alerts = list(item_alerts.values()) + sku_alerts + new_alerts

    for a in alerts:
        # 稳定 ID：不含 change_pct；同商品/同类型/同级别当天复用同一个 ID，
        # 避免价格小幅变化就换 ID 重复推。进一步下跌由 push 冷却逻辑判断。
        a["alert_id"] = _alert_id(date, a["type"], a["entity"], a["product_id"],
                                  a["sku_id"], a["level"])
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
        "notes": notes,
    }
    return {"alerts": alerts, "summary": summary}


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
# _MODULE_DIR 是 model/5.价格告警，退两层才到 
# 影刀把 CodeFlow 复制到 xbot_robot 下执行，相对路径会指到应用目录；
# 因此与 1.列表页采集 同款：环境变量 > 相对仓库 > 本机绝对路径。
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化",
]


def _first_project(candidates):
    for p in candidates:
        if p and os.path.isdir(os.path.join(p, "model")):
            return p
    return os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))


PROJECT_DIR = _first_project(_PROJECT_CANDIDATES)
DEFAULT_CONFIG = os.path.join(PROJECT_DIR, "config", "alert.json")
LOCAL_CONFIG = os.path.join(PROJECT_DIR, "config", "alert_local.json")

DEFAULTS = {
    "thresholds": {
        "drop_pct_daily": 5.0,      # 降价 ≥5% 进日报
        "drop_pct_instant": 10.0,   # 降价 ≥10% 即时推
        "rise_pct_daily": 5.0,
        "rise_pct_instant": 10.0,
        "drop_abs_daily": 5.0,      # 降价绝对值 ≥5 元也进日报（0=关闭）
        "drop_abs_instant": 20.0,   # 降价绝对值 ≥20 元也即时（0=关闭）
        "rise_abs_daily": 5.0,
        "rise_abs_instant": 20.0,
        "new_low_instant": True,    # 创新低即使 <10% 也即时推
    },
    # 去重 / 冷却：稳定 alert_id + 24h 内不重复推；继续跌破 re_alert_pct 才再报
    "dedup": {
        "cooldown_hours": 24,
        "re_alert_pct": 3.0,
    },
    "new_product": {
        "enabled": True,
        "top_n": 10,                # 按销量取头部
        "days": 7,                  # 最近 N 天首次出现算新品
        "min_history_days": 3,      # 历史不足 3 天不判"进头部"（首跑全是新品）
    },
    "channels": {
        "default": "file",
        "file": {"type": "file", "dir": "runtime/alerts"},
        "feishu": {"type": "feishu", "url": "${FEISHU_WEBHOOK}"},
    },
    "send_instant": True,           # --send 时是否发即时告警
    "send_daily": False,            # --send 时是否连日报一起发
}


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_env(value):
    """'${VAR}' / 'env:VAR' -> 环境变量值；解析不到返回空串。"""
    if not isinstance(value, str):
        return value
    s = value.strip()
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", s) or \
        re.fullmatch(r"env:([A-Za-z_][A-Za-z0-9_]*)", s)
    if m:
        return os.environ.get(m.group(1), "")
    return value


def load(path=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    for p in (path or DEFAULT_CONFIG, None if path else LOCAL_CONFIG):
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
    # 占位符解析
    for name, ch in (cfg.get("channels") or {}).items():
        if isinstance(ch, dict):
            for key in ("url", "secret", "keyword"):
                if key in ch:
                    ch[key] = resolve_env(ch[key])
    return cfg





def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
