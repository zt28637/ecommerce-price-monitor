"""列表层清洗：list_raw JSONL -> 商品级候选行（item 的列表半边）。

输入（collect_list 落盘，一行一个商品）：
  runtime/v2/list_raw/<关键词>/<YYYYMMDD_HHMM>.jsonl
  product_id, title, price, price_raw, sales, shop_name, prov_city,
  main_image_url, detail_url, platform, is_promoted,
  passed / filter_reason（可选：缺 passed 视为通过；只有旧 AI 稿的全量落盘才带 False）

做四件事：
  1. 结构归一（ID 文本、价格 float、销量只认「数字(+万)+人收货/付款」）
  2. crawl_date / crawl_ts 从文件名取（列表行本身没有采集日期）
  3. 去重：(product_id, crawl_date) 取最新一轮；同日重复进 anomalies
  4. 过滤行不丢：passed=False 的行写进 anomalies（disposition=filtered）

不做：合并详情、判质量等级 —— 分别归 clean_merge / rules.apply_grades。
"""

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import export
from rules import (crawl_date_from_ts, crawl_ts_from_filename, norm_id,
                   norm_sales, norm_text, norm_url, to_float, valid_product_id)


# ------------------------------------------------------------
# 单行
# ------------------------------------------------------------
def clean_row(raw, crawl_date, crawl_ts, source_file=""):
    """原始列表行 -> 清洗行（纯函数）。"""
    pid = norm_id(raw.get("product_id"))
    price = to_float(raw.get("price"))
    if price is None:
        price = to_float(raw.get("price_raw"))   # 解析层已尽量给数值，这里只兜底
    sales, sales_flag = norm_sales(raw.get("sales"))

    return {
        "crawl_date": crawl_date,
        "product_id": pid,
        "title": norm_text(raw.get("title")),
        "price_list": price,
        "price_list_raw": norm_text(raw.get("price_raw")),
        "price_list_flag": "price_missing" if price is None else "",
        "sales": sales,
        "sales_raw": norm_text(raw.get("sales")),
        "sales_flag": sales_flag,
        "shop_name": norm_text(raw.get("shop_name")),
        "prov_city": norm_text(raw.get("prov_city")) or " ".join(
            p for p in (norm_text(raw.get("prov")), norm_text(raw.get("city"))) if p),
        "main_image_url": norm_url(raw.get("main_image_url")),
        "detail_url": norm_text(raw.get("detail_url")),
        "platform": norm_text(raw.get("platform")) or "unknown",
        "is_promoted": 1 if raw.get("is_promoted") else 0,
        # 缺 passed 视为通过：手写版列表层 filter_product 先过滤、只落通过行，
        # 落盘里不存在 passed=False 的行。仅当上游显式写了 False（旧 AI 稿的全量落盘）
        # 才按过滤行处理，走 anomalies。
        "passed": raw.get("passed") is not False,
        "filter_reason": norm_text(raw.get("filter_reason")),
        "list_ts": crawl_ts,
        "source_file": os.path.basename(source_file),
    }


def _anomaly(row, rule, level, disposition, message, payload=None):
    return {
        "crawl_date": row.get("crawl_date"),
        "product_id": row.get("product_id"),
        "sku_id": "",
        "level": level,
        "rule": rule,
        "message": message,
        "disposition": disposition,
        "source_file": row.get("source_file", ""),
        "crawl_ts": row.get("list_ts", ""),
        "payload": payload or {
            "title": row.get("title"),
            "price": row.get("price_list"),
            "price_raw": row.get("price_list_raw"),
            "sales_raw": row.get("sales_raw"),
            "filter_reason": row.get("filter_reason"),
        },
    }


# ------------------------------------------------------------
# 文件级
# ------------------------------------------------------------
def read_file(path):
    """读一份 list_raw JSONL，日期/轮次取自文件名。返回 (rows, stats)。"""
    ts = crawl_ts_from_filename(path)
    day = crawl_date_from_ts(ts)
    raw_rows, bad = export.read_jsonl(path)
    rows = [clean_row(r, day, ts, path) for r in raw_rows]
    return rows, {"file": os.path.basename(path), "ts": ts, "date": day,
                  "rows": len(rows), "bad_lines": bad}


def clean_files(paths, date=None):
    """多份 JSONL -> {'items','anomalies','stats'}。

    paths 可以是文件或目录（目录取其中全部 .jsonl）。
    date 给定时只保留该采集日期（跨日补跑按实际日期落库）。
    """
    files = []
    for p in paths:
        if os.path.isdir(p):
            for dirpath, _, names in os.walk(p):
                files.extend(sorted(os.path.join(dirpath, n) for n in names
                                    if n.endswith(".jsonl")))
        elif p:
            files.append(p)

    rows, anomalies, files_stats = [], [], []
    for p in files:
        got, st = read_file(p)
        if date:
            kept = [r for r in got if r["crawl_date"] == date]
            st["dropped_other_date"] = len(got) - len(kept)
            got = kept
        st["kept"] = len(got)
        rows.extend(got)
        files_stats.append(st)

    items, dup_anomalies, dup_stats = dedupe(rows)
    anomalies.extend(dup_anomalies)

    passed, filtered = [], []
    for r in items:
        if r["passed"]:
            passed.append(r)
        else:
            filtered.append(r)
            anomalies.append(_anomaly(
                r, "filtered", "info", "filtered",
                "被相关性过滤：%s" % (r.get("filter_reason") or "unknown")))

    stats = {
        "files": files_stats,
        "raw_rows": len(rows),
        "deduped": len(items),
        "passed": len(passed),
        "filtered": len(filtered),
        "filter_reasons": {},
        **dup_stats,
    }
    for r in filtered:
        k = r.get("filter_reason") or "unknown"
        stats["filter_reasons"][k] = stats["filter_reasons"].get(k, 0) + 1

    # 只有 passed 的行进入 item 表；列表侧没有详情的商品由 clean_merge 接受
    return {"items": passed, "filtered": filtered, "anomalies": anomalies, "stats": stats}


# ------------------------------------------------------------
# 去重：(product_id, crawl_date) 取最新一轮
# ------------------------------------------------------------
def dedupe(rows):
    """同商品同日只留最新一轮。返回 (kept, anomalies, stats)。

    「最新有效轮」= 轮次时间最大且 product_id 合法的那条。
    不因为最新轮价格为空就回退到旧轮 —— 那会把旧价伪装成今天的最新观测。
    """
    anomalies = []
    best = {}
    dup_count = 0

    for r in rows:
        key = (r["product_id"], r["crawl_date"])
        if not valid_product_id(r["product_id"]):
            anomalies.append(_anomaly(r, "missing_key", "red", "dropped",
                                      "商品 ID 缺失或非法"))
            continue
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        dup_count += 1
        # 选轮次更新的；同轮次保留先出现的（翻页重叠）
        if r["list_ts"] > cur["list_ts"]:
            loser = cur
            best[key] = r
        else:
            loser = r
        anomalies.append({
            "crawl_date": loser["crawl_date"],
            "product_id": loser["product_id"],
            "sku_id": "",
            "level": "info",
            "rule": "dup_replaced",
            "message": "同日重复轮次，保留 %s，丢弃 %s" % (best[key]["list_ts"], loser["list_ts"]),
            "disposition": "kept_latest",
            "source_file": loser.get("source_file", ""),
            "crawl_ts": loser.get("list_ts", ""),
            "payload": {"price": loser.get("price_list"),
                        "price_raw": loser.get("price_list_raw")},
        })

    kept = sorted(best.values(), key=lambda x: (x["crawl_date"], x["product_id"]))
    return kept, anomalies, {"duplicate_rows": dup_count, "unique_keys": len(kept)}


# ------------------------------------------------------------
# 影刀入口（预留）
# ------------------------------------------------------------
def main(args=None):
    args = args or {}
    paths = args.get("paths") or [args.get("path") or ""]
    return clean_files([p for p in paths if p], date=args.get("date"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    root = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\runtime\_sample\list_raw"
    got = clean_files([root], date=None)
    print("文件:", [f["file"] for f in got["stats"]["files"]])
    s = got["stats"]
    print("raw %(raw_rows)d -> 去重 %(deduped)d -> 通过 %(passed)d / 过滤 %(filtered)d" % s)
    print("过滤原因:", s["filter_reasons"])
    for r in got["items"][:5]:
        print(" ", r["product_id"], r["title"][:18], r["price_list"], r["sales"], r["sales_flag"])
