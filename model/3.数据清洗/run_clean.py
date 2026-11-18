"""清洗总入口：list_raw + detail_raw -> clean/<YYYYMMDD>/ 产物 + 一份 Excel 日报。

用法（系统 Python，不依赖影刀 venv）：
  python run_clean.py --date YYYY-MM-DD \
      --list-raw  runtime/_sample/list_raw \
      --detail-raw runtime/_sample/detail_raw

  # 没有 list_raw 时，可从已保存的列表页 HTML 现生成（回归用）
  python run_clean.py --date YYYY-MM-DD --list-html runtime/_sample/x.html \
      --list-ts YYYYMMDD_HHMM --detail-raw runtime/_sample/detail_raw

流程（顺序不能换）：
  读 list -> 清洗去重 -> 读 detail -> 清洗去重 -> 合并 item
  -> 红黄绿分级（红行剔除）-> 落盘 -> 报表

不做：入库、登录、画布、详情采集。人工核对看 日报_<date>.xlsx。
"""

import argparse
import datetime
import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_TOOL_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "tool"))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)
if _TOOL_DIR not in sys.path:
    sys.path.insert(0, _TOOL_DIR)

import paths

import clean_detail
import clean_list
import clean_merge
import export
import input_clean
import verify_clean
import rules

DEFAULT_ROOT = paths.RUNTIME
DEFAULT_CONFIG = input_clean.DEFAULT_CONFIG


def _log(msg):
    print(msg)
    sys.stdout.flush()


# ------------------------------------------------------------
# 从 HTML 现生成 list_raw（回归 / 补跑）
# ------------------------------------------------------------
def generate_list_raw(*a, **kw):
    """兼容旧调用：转 N3.1 input_clean。"""
    return input_clean.generate_list_raw(*a, **kw)


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def run(args):
    inp = input_clean.resolve(args, DEFAULT_ROOT)
    cfg = inp["cfg"]
    root = inp["root"]
    date = inp["date"]
    out_dir = inp["out_dir"]

    # 1) 列表
    lst = clean_list.clean_files(inp["list_paths"], date=date)
    _log("[清洗] 列表：原始 %(raw_rows)d -> 去重 %(deduped)d -> 通过 %(passed)d / 过滤 %(filtered)d"
         % lst["stats"])

    # 2) 详情
    det = clean_detail.clean_files(inp["detail_paths"], date=date, cfg=cfg)
    _log("[清洗] 详情：原始 %(raw_rows)d -> 商品 %(products)d | 有价 SKU %(skus_priced)d"
         " | 无价库存 %(inventory_rows)d" % det["stats"])

    # 3) 合并
    items, merge_anomalies = clean_merge.merge(lst["items"], det["item_details"], det["skus"])
    _log("[清洗] 合并：item %d 行（both %d / list_only %d / detail_only %d）" % (
        len(items),
        sum(1 for r in items if r["merge_status"] == "both"),
        sum(1 for r in items if r["merge_status"] == "list_only"),
        sum(1 for r in items if r["merge_status"] == "detail_only")))

    # 4) 分级（红行在此剔除；黄标保留，问题记在 flags）
    anomalies = lst["anomalies"] + det["anomalies"] + merge_anomalies
    qres = rules.apply_grades(items, det["skus"], det["inventory"], cfg, anomalies)
    qstats = qres["stats"]
    _log("[清洗] 分级：item 绿 %(item_green)d / 黄 %(item_yellow)d / 红 %(item_red)d | "
         "sku 绿 %(sku_green)d / 黄 %(sku_yellow)d / 红 %(sku_dropped)d" % qstats)

    # 5) 落盘
    export.write_jsonl(os.path.join(out_dir, "item.jsonl"), qres["items"])
    export.write_jsonl(os.path.join(out_dir, "sku.jsonl"), qres["skus"])
    export.write_jsonl(os.path.join(out_dir, "inventory.jsonl"), qres["inventory"])
    export.write_jsonl(os.path.join(out_dir, "anomalies.jsonl"), qres["anomalies"])
    export.write_xlsx(os.path.join(out_dir, "item.xlsx"),
                      [("item", qres["items"], export.ITEM_COLUMNS)])
    export.write_xlsx(os.path.join(out_dir, "sku.xlsx"),
                      [("sku", qres["skus"], export.SKU_COLUMNS)])

    # 6) 日报（人工核对入口）
    extra = {
        "list": {k: v for k, v in lst["stats"].items() if k != "files"},
        "detail": {k: v for k, v in det["stats"].items() if k != "files"},
    }
    report_path = export.save_report(date, qres["items"], qres["skus"], qres["inventory"],
                              qres["anomalies"], out_dir, qstats, extra)

    output_files = [os.path.join(out_dir, n) for n in
                    ("item.jsonl", "item.xlsx", "sku.jsonl", "sku.xlsx",
                     "inventory.jsonl", "anomalies.jsonl")]
    meta = verify_clean.build_meta(date, out_dir, args, qstats,
                                   lst["stats"], det["stats"],
                                   report_path, output_files)
    verify_clean.write_meta(out_dir, meta)

    _log("[清洗] 产物目录：%s" % out_dir)
    for p in meta["outputs"]:
        _log("        - %s" % os.path.basename(p))
    return {"out_dir": out_dir, "counts": qstats, "meta": meta}


def main(args=None):
    return run(args or {})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v2 数据清洗")
    ap.add_argument("--date", default="", help="采集日期 YYYY-MM-DD；默认今天")
    ap.add_argument("--list-raw", action="append", default=[], help="list_raw 文件或目录，可重复")
    ap.add_argument("--detail-raw", action="append", default=[], help="detail_raw 文件或目录，可重复")
    ap.add_argument("--list-html", action="append", default=[],
                    help="没有 list_raw 时从列表页 HTML 现生成，可重复")
    ap.add_argument("--list-ts", action="append", default=[],
                    help="现生成 JSONL 的轮次号 YYYYMMDD_HHMM，与 --list-html 顺序对应")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="runtime 根目录")
    ap.add_argument("--out", default="", help="输出目录；默认 <root>/clean/<YYYYMMDD>")
    ap.add_argument("--config", default="", help="清洗阈值 JSON（price_min/price_max，可选）")
    ap.add_argument("--targets-config", default="",
                    help="采集目标 targets.json 路径（仅 --list-html 现生成时用；默认 config/targets.json）")
    run(vars(ap.parse_args()))
