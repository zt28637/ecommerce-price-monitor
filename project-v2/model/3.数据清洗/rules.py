"""清洗规则：归一化（L1 结构 + L2 业务规则）+ 红黄绿分级。

这一层只做「把一条记录变成可信的值」，不读写文件、不依赖 pandas。
阈值集中在 DEFAULTS，可用 clean.json / CLI 覆盖；代码里不写死。

三条纪律：
  1. 价格一律 float；转不出数字 = None，不补 0、不插值
  2. 销量只认「数字(+万)+人收货/付款」；其余置 None 并打 sales_non_numeric
     —— 裸 (\\d+) 会把「行业销量前20」里的 20 当成销量
  3. 打标不丢弃：每条异常都要能追到 rule / 原始值 / 来源文件
"""

import datetime
import json
import math
import os
import re

# ------------------------------------------------------------
# 默认参数
# ------------------------------------------------------------
DEFAULTS = {
    "price_min": 1.0,
    "price_max": 100000.0,
}

# ------------------------------------------------------------
# 规则分级
# ------------------------------------------------------------
# 红：阻断，不进 item/sku 表；只留在 anomalies（disposition=dropped）
RED_RULES = {
    "missing_key": "主键缺失或非法",
    "price_nonpositive": "价格 ≤ 0",
    "price_out_of_range": "价格超出 1–100000",
    "key_conflict": "同一主键出现互斥内容",
}

# 黄：保留在表里，flags 记录问题，供人看报表核对
YELLOW_RULES = {
    "price_missing": "价格缺失",
    "price_detail_missing": "详情价缺失（列表价仅作触发器）",
    "sales_missing": "销量缺失",
    "sales_non_numeric": "销量非数值文案",
    "partial_sku": "SKU 价不完整",
}

# 信息：记录事实，不影响分级
INFO_RULES = {
    "filtered": "被相关性过滤",
    "dup_replaced": "同日重复轮次，取最新",
    "price_conflict": "同日同 SKU 价格不一致，取最新完整轮",
    "sku_stale": "该 SKU 未出现在最新一轮",
    "detail_missing": "未深采（仅列表）",
}


# ------------------------------------------------------------
# 基础归一化
# ------------------------------------------------------------
def to_float(v):
    """任意输入 -> float | None。空、'--'、'***'、'暂无' 一律 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("¥", "").replace("￥", "").replace(",", "").replace("，", "")
    try:
        return float(s)
    except ValueError:
        return None


def to_int(v):
    """任意输入 -> int | None。不把 None 当 0。"""
    f = to_float(v)
    return None if f is None else int(f)


def norm_text(v):
    """去首尾空白与零宽字符；None -> ''。"""
    if v is None:
        return ""
    s = str(v)
    s = s.replace("​", "").replace("﻿", "")
    return s.strip()


def norm_id(v):
    """ID 一律 str：去 Excel 前导单引号、去 float 尾巴 .0、去空白。"""
    s = norm_text(v)
    if s.startswith("'"):
        s = s[1:]
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def valid_product_id(pid):
    """商品 ID：纯数字且长度 ≥ 6（淘宝/天猫实测 11–13 位）。"""
    return bool(re.fullmatch(r"\d{6,}", pid or ""))


def valid_sku_id(sid):
    """SKU ID：纯数字，或单规格兜底的 <product_id>__default。"""
    if not sid:
        return False
    if sid.endswith("__default"):
        return valid_product_id(sid.split("__default")[0])
    return bool(re.fullmatch(r"\d+", sid))


def norm_url(u):
    """协议相对地址补 https；其余原样返回（不擅自改写商家链接）。"""
    s = norm_text(u)
    return "https:" + s if s.startswith("//") else s


# ------------------------------------------------------------
# 销量归一（唯一入口）
# ------------------------------------------------------------
# 只认：<数字>[.<小数>][万]+?人(收货|付款)
RE_SALES = re.compile(r"^(\d+(?:\.\d+)?)(万)?\+?人(收货|付款)$")


def norm_sales(raw):
    """销量原文 -> (int|None, flag|'')。

    返回的 flag 只会是 sales_missing（空）或 sales_non_numeric（有字但不认）。
    """
    s = re.sub(r"\s+", "", norm_text(raw))
    if not s:
        return None, "sales_missing"
    m = RE_SALES.match(s)
    if not m:
        return None, "sales_non_numeric"
    num = float(m.group(1))
    if m.group(2):
        num *= 10000.0
    return int(round(num)), ""


# ------------------------------------------------------------
# 时间 / 文件名
# ------------------------------------------------------------
def crawl_date_from_ts(ts):
    """'20261031_2355' / '2026-10-31' -> '2026-10-31'；认不出返回 ''。"""
    s = norm_text(ts)
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:_|$)", s)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return ""


def crawl_ts_from_filename(path):
    """'20261031_2355.jsonl' -> '20261031_2355'；认不出返回 ''。"""
    m = re.match(r"^(\d{8}_\d{4,6})(?:\.|$)", os.path.basename(norm_text(path)))
    return m.group(1) if m else ""


def today_str():
    return datetime.date.today().isoformat()


# ------------------------------------------------------------
# 详情价完整性 / 标记分流
# ------------------------------------------------------------
def infer_price_complete(row):
    """老样本没有 price_complete 字段：用 coverage / flags 反推。

    宁可判 False 也不假装完整 —— 假完整会污染 SKU 趋势。
    """
    pc = row.get("price_complete")
    if isinstance(pc, bool):
        return pc
    m = re.fullmatch(r"(\d+)/(\d+)", norm_text(row.get("price_coverage")))
    if m:
        return int(m.group(2)) > 0 and int(m.group(1)) == int(m.group(2))
    flags = split_flags(row.get("flags"))
    return not any(f in ("partial_sku_price", "masked_price", "sku_count_mismatch")
                   for f in flags)


def split_flags(flags):
    if not flags:
        return []
    if isinstance(flags, str):
        return [f for f in flags.split(";") if f]
    return [str(f) for f in flags if f]


# 上游标记（采集链路）与质量标记分开：api 补价、单规格兜底这些是来源说明，
# 不是质量问题。上游标记进 source_flags，质量列只看 flags，避免报表误读。
KNOWN_QUALITY_FLAGS = set(RED_RULES) | set(YELLOW_RULES) | set(INFO_RULES)

# 上游（详情解析 parse_detail / collect_detail）的旗标名与清洗层词表不一致：
# 不先归一化，partial_sku_price 等旗标会整包落进 source_flags，
# 结果"价格不完整的 SKU 仍判 green"，而 clean_merge 里对应的分支也永远走不到。
# no_sku 不在此表：它是"详情没给 SKU 列表、用商品价兜底单规格"的正常形态，
# 不是缺失，保持信息级。
FLAG_ALIASES = {
    "partial_sku_price": "partial_sku",    # 部分 SKU 无价
    "sku_count_mismatch": "partial_sku",   # 解析出的 SKU 数与页面不一致
    "masked_price": "price_missing",       # 价格被打码 ***
}


def split_quality_flags(flags):
    """-> (quality_flags, source_flags)；上游旗标先归一化到本层词表。"""
    allf = [FLAG_ALIASES.get(f, f) for f in split_flags(flags)]
    quality = [f for f in allf if f in KNOWN_QUALITY_FLAGS]
    source = [f for f in allf if f not in KNOWN_QUALITY_FLAGS]
    return quality, source


# ------------------------------------------------------------
# 分级
# ------------------------------------------------------------
def grade(flags):
    """flags -> 'red' | 'yellow' | 'green'。"""
    fs = set(flags or [])
    if fs & set(RED_RULES):
        return "red"
    if fs & set(YELLOW_RULES):
        return "yellow"
    return "green"


def rule_label(rule):
    return RED_RULES.get(rule) or YELLOW_RULES.get(rule) or INFO_RULES.get(rule) or rule


# ------------------------------------------------------------
# 价格合法性 + 分级落地
# ------------------------------------------------------------
def price_problem(value, cfg, field):
    """-> (rule, message) | None"""
    if value is None:
        return None
    if value <= 0:
        return "price_nonpositive", "%s = %s" % (field, value)
    if not (cfg["price_min"] <= value <= cfg["price_max"]):
        return "price_out_of_range", "%s = %s" % (field, value)
    return None


def _item_red_flags(row, cfg):
    flags, msgs = [], []
    if not valid_product_id(row.get("product_id")):
        flags.append("missing_key")
        msgs.append("商品 ID 非法：%r" % row.get("product_id"))
    for field in ("price_list", "price_detail", "min_sku_price", "max_sku_price"):
        p = price_problem(row.get(field), cfg, field)
        if p:
            flags.append(p[0])
            msgs.append(p[1])
    if "key_conflict" in (row.get("flags") or []):
        flags.append("key_conflict")
        msgs.append("主键互斥冲突")
    return flags, msgs


def _sku_red_flags(row, cfg):
    flags, msgs = [], []
    if not valid_sku_id(row.get("sku_id")) or not valid_product_id(row.get("product_id")):
        flags.append("missing_key")
        msgs.append("SKU/商品 ID 非法")
    p = price_problem(row.get("price"), cfg, "price")
    if p:
        flags.append(p[0])
        msgs.append(p[1])
    if "key_conflict" in (row.get("flags") or []):
        flags.append("key_conflict")
        msgs.append("SKU 身份冲突")
    return flags, msgs


def _anomaly(row, rule, level, disposition, message):
    return {
        "crawl_date": row.get("crawl_date"),
        "product_id": row.get("product_id", ""),
        "sku_id": row.get("sku_id", ""),
        "level": level,
        "rule": rule,
        "message": message,
        "disposition": disposition,
        "source_file": row.get("source_file", ""),
        "crawl_ts": row.get("crawl_ts") or row.get("detail_ts") or row.get("list_ts") or "",
        "payload": {
            "title": row.get("title"),
            "price_list": row.get("price_list"),
            "price_detail": row.get("price_detail"),
            "price": row.get("price"),
            "price_raw": row.get("price_raw") or row.get("price_detail_raw") or row.get("price_list_raw"),
            "sales_raw": row.get("sales_raw"),
            "flags": row.get("flags"),
        },
    }


def apply_grades(items, skus, inventory, cfg, extra_anomalies=None):
    """剔除红行，给保留行打 quality / review_status。

    保留行一律 review_status='auto_pass'（不再有复核单）：问题只记在 flags 与
    quality 里，人工看报表核对；下游按 quality 自行过滤，不靠人工放行。
    """
    anomalies = list(extra_anomalies or [])
    rule_hits = {}
    dropped = []
    kept_items, kept_skus = [], []

    def _hit(flags):
        for f in flags:
            rule_hits[f] = rule_hits.get(f, 0) + 1

    for it in items:
        red, msgs = _item_red_flags(it, cfg)
        if red:
            for f, msg in zip(red, msgs):
                _hit([f])
                anomalies.append(_anomaly(it, f, "red", "dropped", msg))
            dropped.append(("item", it))
            continue
        it["flags"] = sorted(set(it.get("flags") or []))
        _hit(it["flags"])
        it["quality"] = grade(it["flags"])
        it["review_status"] = "auto_pass"
        for f in it["flags"]:
            if f in YELLOW_RULES:
                anomalies.append(_anomaly(it, f, "yellow", "kept",
                                          "保留并打标：%s" % rule_label(f)))
        kept_items.append(it)

    for s in skus:
        red, msgs = _sku_red_flags(s, cfg)
        if red:
            for f, msg in zip(red, msgs):
                _hit([f])
                anomalies.append(_anomaly(s, f, "red", "dropped", msg))
            dropped.append(("sku", s))
            continue
        s["flags"] = sorted(set(s.get("flags") or []))
        _hit(s["flags"])
        s["quality"] = grade(s["flags"])
        s["review_status"] = "auto_pass"
        for f in s["flags"]:
            if f in YELLOW_RULES:
                anomalies.append(_anomaly(s, f, "yellow", "kept",
                                          "保留并打标：%s" % rule_label(f)))
        kept_skus.append(s)

    # 无价库存：不进趋势、不逐行记 anomalies（会冲垮队列），按商品聚合一条 info。
    kept_inv, inv_by_pid = [], {}
    for v in inventory:
        v["flags"] = sorted(set((v.get("flags") or []) + ["price_missing"]))
        v["quality"] = "yellow"
        v["review_status"] = "auto_pass"
        kept_inv.append(v)
        inv_by_pid.setdefault(v["product_id"], []).append(v)
    for pid, rows in sorted(inv_by_pid.items()):
        anomalies.append({
            "crawl_date": rows[0]["crawl_date"], "product_id": pid, "sku_id": "",
            "level": "info", "rule": "price_missing",
            "message": "无价库存 %d 个 SKU（%s），保留库存事实、不进价格趋势"
                       % (len(rows), rows[0].get("reason") or "price_null"),
            "disposition": "kept", "source_file": rows[0].get("source_file", ""),
            "crawl_ts": rows[0].get("crawl_ts", ""),
            "payload": {"skus": [r["sku_id"] for r in rows],
                        "quantities": [r.get("quantity") for r in rows]},
        })

    green = sum(1 for r in kept_items if r["quality"] == "green")
    stats = {
        "item_total": len(items),
        "item_green": green,
        "item_yellow": sum(1 for r in kept_items if r["quality"] == "yellow"),
        "item_red": sum(1 for kind, _ in dropped if kind == "item"),
        "sku_total": len(skus),
        "sku_green": sum(1 for r in kept_skus if r["quality"] == "green"),
        "sku_yellow": sum(1 for r in kept_skus if r["quality"] == "yellow"),
        "sku_dropped": sum(1 for kind, _ in dropped if kind == "sku"),
        "inventory_rows": len(kept_inv),
        "rule_hits": rule_hits,
        "pass_rate": (green / float(len(kept_items))) if kept_items else 0.0,
    }
    return {"items": kept_items, "skus": kept_skus, "inventory": kept_inv,
            "dropped": dropped, "anomalies": anomalies, "stats": stats}


# ------------------------------------------------------------
# 配置
# ------------------------------------------------------------
def load_config(path=None):
    """DEFAULTS + 可选 JSON 覆盖（浅合并）。"""
    cfg = json.loads(json.dumps(DEFAULTS))
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f) or {})
    return cfg


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    for c in ["2000+人付款", "3万+人付款", "1.2万人收货", "行业销量前20",
              "本月行业热销", "", None, "7000+人收货"]:
        print("%-12r -> %s" % (c, norm_sales(c)))
    print("date 20261031_2355 ->", crawl_date_from_ts("20261031_2355"))
    print("price '--' ->", to_float("--"), "| '¥1,299.00' ->", to_float("¥1,299.00"))
    print("grade", grade(["sales_missing"]), grade(["missing_key"]),
          grade(["sales_missing", "missing_key"]))
