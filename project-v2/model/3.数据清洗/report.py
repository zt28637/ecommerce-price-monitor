"""日报：一份 Excel 工作簿（概览 / 商品 / SKU / 库存 / 异常）。

人工核对就看这一份：概览说明本次抓了多少、哪几类问题最多；异常页保留
所有红标丢弃 / 黄标打标 / 过滤原因，不静默丢数据。
"""

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import export
from export import INVENTORY_COLUMNS, ITEM_COLUMNS, SKU_COLUMNS

SUMMARY_COLUMNS = [("metric", "指标", 26), ("value", "数值", 22), ("note", "说明", 56)]
ANOMALY_COLUMNS = [
    ("crawl_date", "采集日期", 12),
    ("level", "级别", 8),
    ("rule", "规则", 18),
    ("product_id", "商品ID", 16),
    ("sku_id", "SKU ID", 18),
    ("message", "说明", 60),
    ("disposition", "处置", 12),
    ("crawl_ts", "采集轮次", 14),
    ("source_file", "来源文件", 28),
]


def _pct(v):
    try:
        return "%.1f%%" % (float(v) * 100)
    except (TypeError, ValueError):
        return "-"


def summary_rows(date, stats, extra):
    lst = (extra or {}).get("list") or {}
    det = (extra or {}).get("detail") or {}
    rows = [
        {"metric": "采集日期", "value": date, "note": ""},
        {"metric": "商品·天", "value": stats.get("item_total"), "note": "item 表行数"},
        {"metric": "绿 / 黄 / 红", "value": "%s / %s / %s" % (
            stats.get("item_green"), stats.get("item_yellow"), stats.get("item_red")),
         "note": "红标不进表；黄标保留，见 flags / 异常页"},
        {"metric": "通过率", "value": _pct(stats.get("pass_rate")), "note": "绿 / 商品总数"},
        {"metric": "有价 SKU", "value": (stats.get("sku_green") or 0)
         + (stats.get("sku_yellow") or 0), "note": "sku 表"},
        {"metric": "无价库存", "value": stats.get("inventory_rows"),
         "note": "inventory 表；不记 0 价、不进趋势"},
        {"metric": "列表原始 / 去重 / 通过", "value": "%s / %s / %s" % (
            lst.get("raw_rows", "-"), lst.get("deduped", "-"), lst.get("passed", "-")),
         "note": "来自 list_raw"},
        {"metric": "详情原始 / 商品 / 有价 SKU", "value": "%s / %s / %s" % (
            det.get("raw_rows", "-"), det.get("products", "-"), det.get("skus_priced", "-")),
         "note": "来自 detail_raw"},
    ]
    for k, v in sorted((stats.get("rule_hits") or {}).items(), key=lambda x: -x[1]):
        rows.append({"metric": "规则:" + k, "value": v, "note": ""})
    return rows


def anomaly_rows(anomalies):
    return list(anomalies or [])


def save(date, items, skus, inventory, anomalies, out_dir, stats, extra=None):
    """写 日报_<date>.xlsx，返回路径。"""
    out_dir = export.ensure_dir(out_dir)
    path = os.path.join(out_dir, "日报_%s.xlsx" % date)
    export.write_xlsx(path, [
        ("概览", summary_rows(date, stats, extra), SUMMARY_COLUMNS),
        ("商品", items, ITEM_COLUMNS),
        ("SKU", skus, SKU_COLUMNS),
        ("库存", inventory, INVENTORY_COLUMNS),
        ("异常", anomaly_rows(anomalies), ANOMALY_COLUMNS),
    ])
    return path


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("report.py: 由 run_clean 调用；单独运行请见 run_clean.py --help")
