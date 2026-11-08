"""详情层清洗：detail_raw JSONL（一行一个 SKU）-> item_detail + sku + inventory。

输入：
  crawl_date, crawl_ts, product_id, title, shop, item_price, item_price_raw,
  price_desc, item_price_scope, hide_other_price, price_coverage, price_complete,
  flags, sku_id, prop_path, prop_names, price, price_raw, quantity,
  quantity_text, in_stock, retry_count

输出三份（粒度不同，不压平）：
  item_details  商品·天，1 行（商品起售价/默认价、完整性、SKU 计数）
  skus          有价 SKU·天（价格表）
  inventory     无价 SKU·天（库存事实；不进价格趋势，不记 0 价）

去重规则（用户 11-01 定）：
  · (product_id, sku_id, crawl_date) 优先最新 price_complete=true 的一行
  · 没有完整轮才退到最新的一行，并保留 price_complete=false
  · 不做「最后一条无条件覆盖」——那会让半价的失败轮盖掉完整轮
"""

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import export
from rules import (crawl_date_from_ts, crawl_ts_from_filename, infer_price_complete,
                   norm_id, norm_text, split_flags, split_quality_flags,
                   to_float, to_int, valid_product_id)


# ------------------------------------------------------------
# 单行
# ------------------------------------------------------------
def _default_sku_id(product_id):
    """单规格商品兜底：parse_detail 给空 sku_id，这里补 <product_id>__default。"""
    return "%s__default" % product_id


def clean_row(raw, crawl_date, crawl_ts, source_file=""):
    pid = norm_id(raw.get("product_id"))
    sid = norm_id(raw.get("sku_id")) or _default_sku_id(pid)
    price = to_float(raw.get("price"))
    qty = to_int(raw.get("quantity"))
    in_stock = raw.get("in_stock")
    if not isinstance(in_stock, bool):
        in_stock = None if qty is None else qty > 0

    all_flags = split_flags(raw.get("flags"))
    flags, source_flags = split_quality_flags(all_flags)
    reason = ""
    if price is None and "partial_sku_price" in all_flags:
        reason = "partial_sku_price"
    elif price is None and "masked_price" in all_flags:
        reason = "masked_price"
    elif price is None and norm_text(raw.get("price_raw")):
        reason = "price_unparsed"
    elif price is None:
        reason = "price_null"

    return {
        "crawl_date": crawl_date,
        "crawl_ts": crawl_ts,
        "product_id": pid,
        "sku_id": sid,
        "title": norm_text(raw.get("title")),
        "shop": norm_text(raw.get("shop")),
        "item_price": to_float(raw.get("item_price")),
        "item_price_raw": norm_text(raw.get("item_price_raw")),
        "price_desc": norm_text(raw.get("price_desc")),
        "item_price_scope": norm_text(raw.get("item_price_scope")) or "unknown",
        "hide_other_price": str(raw.get("hide_other_price")).lower() == "true",
        "price_coverage": norm_text(raw.get("price_coverage")),
        "price_complete": infer_price_complete(raw),
        "flags": flags,
        "source_flags": source_flags,
        "url": norm_text(raw.get("url")),
        "retry_count": to_int(raw.get("retry_count")),
        "prop_path": norm_text(raw.get("prop_path")),
        "prop_names": norm_text(raw.get("prop_names")),
        "price": price,
        "price_raw": norm_text(raw.get("price_raw")),
        "quantity": qty,
        "quantity_text": norm_text(raw.get("quantity_text")),
        "in_stock": in_stock,
        "reason": reason,
        "source_file": os.path.basename(source_file),
    }


# ------------------------------------------------------------
# 读文件
# ------------------------------------------------------------
def read_file(path, date=None):
    raw_rows, bad = export.read_jsonl(path)
    f_ts = crawl_ts_from_filename(path)
    f_date = crawl_date_from_ts(f_ts)

    rows, skipped = [], 0
    for raw in raw_rows:
        ts = norm_text(raw.get("crawl_ts")) or f_ts
        day = norm_text(raw.get("crawl_date")) or crawl_date_from_ts(ts) or f_date
        if date and day != date:
            skipped += 1
            continue
        rows.append(clean_row(raw, day, ts, path))
    return rows, {"file": os.path.basename(path), "rows": len(rows),
                  "bad_lines": bad, "skipped_other_date": skipped}


def clean_files(paths, date=None):
    """多份 detail_raw -> {'item_details','skus','inventory','anomalies','stats'}。"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, _, names in os.walk(p):
                files.extend(sorted(os.path.join(dirpath, n) for n in names
                                    if n.endswith(".jsonl")))
        elif p:
            files.append(p)

    rows, anomalies, file_stats = [], [], []
    for p in files:
        got, st = read_file(p, date=date)
        rows.extend(got)
        file_stats.append(st)

    rows, conflict_anomalies = detect_conflicts(rows)
    anomalies.extend(conflict_anomalies)

    kept, dup_anomalies, dup_stats = dedupe_skus(rows)
    anomalies.extend(dup_anomalies)

    item_details, item_anomalies = build_items(kept)
    anomalies.extend(item_anomalies)

    skus = [r for r in kept if r["price"] is not None]
    inventory = [r for r in kept if r["price"] is None]

    stats = {
        "files": file_stats,
        "raw_rows": len(rows),
        "products": len(item_details),
        "sku_rows": len(kept),
        "skus_priced": len(skus),
        "inventory_rows": len(inventory),
        "red_conflicts": sum(1 for a in anomalies if a["level"] == "red"),
        **dup_stats,
    }
    return {"item_details": item_details, "skus": skus, "inventory": inventory,
            "anomalies": anomalies, "stats": stats}


# ------------------------------------------------------------
# 身份冲突：同一 sku_id 挂在不同商品/规格上
# ------------------------------------------------------------
def detect_conflicts(rows):
    """同一 sku_id 出现互斥身份 -> 打 key_conflict（红，禁入库）。"""
    seen = {}
    for r in rows:
        sid = r["sku_id"]
        ident = (r["product_id"], r["prop_names"])
        seen.setdefault(sid, set()).add(ident)

    bad = {sid for sid, idents in seen.items() if len(idents) > 1}
    anomalies = []
    for r in rows:
        if r["sku_id"] in bad:
            r["flags"].append("key_conflict")
            anomalies.append(_anomaly(r, "key_conflict", "red", "dropped",
                                      "SKU %s 身份冲突：%s" % (
                                          r["sku_id"], sorted(seen[r["sku_id"]]))))
    return rows, anomalies


# ------------------------------------------------------------
# 去重：优先最新完整轮
# ------------------------------------------------------------
def _row_score(r):
    """越大越优先：完整 > 有价 > 轮次新。"""
    return (1 if r["price_complete"] else 0,
            1 if r["price"] is not None else 0,
            r["crawl_ts"])


def dedupe_skus(rows):
    best, anomalies = {}, []
    dup = 0
    for r in rows:
        key = (r["product_id"], r["sku_id"], r["crawl_date"])
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        dup += 1
        if _row_score(r) > _row_score(cur):
            loser, best[key] = cur, r
        else:
            loser = r
        # 价格不一致且两轮都完整 -> 记一笔（不静默选一个）
        if (loser["price"] is not None and best[key]["price"] is not None
                and loser["price_complete"] and best[key]["price_complete"]
                and abs(loser["price"] - best[key]["price"]) > 0.01):
            anomalies.append(_anomaly(
                loser, "price_conflict", "info", "kept_latest",
                "同日同 SKU 价格不一致：%.2f(%s) vs %.2f(%s)" % (
                    loser["price"], loser["crawl_ts"],
                    best[key]["price"], best[key]["crawl_ts"])))

    # 最新一轮里没出现的 SKU -> 信息标记（可能已下架/该轮只返回部分）
    latest_ts = {}
    for r in rows:
        k = (r["product_id"], r["crawl_date"])
        latest_ts[k] = max(latest_ts.get(k, ""), r["crawl_ts"])
    for r in best.values():
        if r["crawl_ts"] < latest_ts.get((r["product_id"], r["crawl_date"]), ""):
            r["flags"].append("sku_stale")

    kept = sorted(best.values(), key=lambda x: (x["crawl_date"], x["product_id"], x["sku_id"]))
    return kept, anomalies, {"duplicate_sku_rows": dup, "unique_skus": len(kept)}


# ------------------------------------------------------------
# 商品级汇总（item 的详情半边）
# ------------------------------------------------------------
def _item_score(r):
    return (1 if r["price_complete"] else 0,
            1 if r["item_price"] is not None else 0,
            r["crawl_ts"])


def build_items(rows):
    """每个 (product_id, crawl_date) 出一条 item_detail。

    item 的价格用「该商品最可信那一轮」的商品价；SKU 计数用去重后的实际行数，
    避免不同轮次 SKU 数不一致时给出假的 coverage。
    """
    groups = {}
    for r in rows:
        groups.setdefault((r["product_id"], r["crawl_date"]), []).append(r)

    items, anomalies = [], []
    for (pid, day), rs in sorted(groups.items()):
        pick = max(rs, key=_item_score)
        # 任一 SKU 身份冲突 -> 整个商品禁入库（冲突行不参与 min/max）
        conflict = any("key_conflict" in (r.get("flags") or []) for r in rs)
        priced = [r for r in rs if r["price"] is not None
                  and not (conflict and "key_conflict" in (r.get("flags") or []))]
        # 0 价 SKU（赠品/占位/"联系客服"）不是有效价格点：只参与有价计数，
        # 不进 min/max —— 否则 min_sku_price=0 会被 price_nonpositive 判红，
        # 一个占位 SKU 就能把整个商品从当天数据里抹掉。
        prices = [r["price"] for r in priced if r["price"] > 0]
        flags = list(pick["flags"])
        if not pick["price_complete"] and "partial_sku" not in flags:
            flags.append("partial_sku")
        if conflict:
            flags.append("key_conflict")

        item = {
            "crawl_date": day,
            "product_id": pid,
            "title": pick["title"],
            "shop": pick["shop"],
            "item_price": pick["item_price"],
            "item_price_raw": pick["item_price_raw"],
            "price_desc": pick["price_desc"],
            "item_price_scope": pick["item_price_scope"],
            "hide_other_price": pick["hide_other_price"],
            "price_coverage": pick["price_coverage"],
            "price_complete": pick["price_complete"],
            "detail_ts": pick["crawl_ts"],
            "url": pick["url"],
            "retry_count": pick["retry_count"],
            "sku_count": len(rs),
            "priced_sku_count": len(priced),
            "min_sku_price": min(prices) if prices else None,
            "max_sku_price": max(prices) if prices else None,
            "flags": sorted(set(flags)),
            "source_file": pick["source_file"],
        }
        items.append(item)

        if not valid_product_id(pid):
            anomalies.append(_anomaly(pick, "missing_key", "red", "dropped",
                                      "商品 ID 缺失或非法（详情）"))
        if item["item_price"] is not None and item["item_price"] <= 0:
            anomalies.append(_anomaly(pick, "price_nonpositive", "red", "dropped",
                                      "商品价 ≤ 0：%s" % item["item_price"]))
    return items, anomalies


# ------------------------------------------------------------
# 小工具
# ------------------------------------------------------------
def _anomaly(row, rule, level, disposition, message, payload=None):
    return {
        "crawl_date": row.get("crawl_date"),
        "product_id": row.get("product_id"),
        "sku_id": row.get("sku_id", ""),
        "level": level,
        "rule": rule,
        "message": message,
        "disposition": disposition,
        "source_file": row.get("source_file", ""),
        "crawl_ts": row.get("crawl_ts", ""),
        "payload": payload or {
            "title": row.get("title"),
            "prop_names": row.get("prop_names"),
            "price": row.get("price"),
            "price_raw": row.get("price_raw"),
            "price_coverage": row.get("price_coverage"),
            "flags": row.get("flags"),
        },
    }


def main(args=None):
    args = args or {}
    paths = args.get("paths") or [args.get("path") or ""]
    return clean_files([p for p in paths if p], date=args.get("date"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    root = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2\runtime\_sample\detail_raw"
    got = clean_files([root], date="2026-11-01")
    s = got["stats"]
    print("详情行 %(raw_rows)d -> 商品 %(products)d | 有价SKU %(skus_priced)d | 无价库存 %(inventory_rows)d"
          % s)
    for it in got["item_details"]:
        print(" ", it["product_id"], "price", it["item_price"], it["item_price_scope"],
              "complete", it["price_complete"], "sku", it["priced_sku_count"], "/", it["sku_count"],
              "min", it["min_sku_price"])
