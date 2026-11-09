"""清洗总入口：list_raw + detail_raw -> clean/<YYYYMMDD>/ 产物 + 一份 Excel 日报。

用法（系统 Python，不依赖影刀 venv）：
  python run_clean.py --date 2026-11-01 \
      --list-raw  runtime/_sample/list_raw \
      --detail-raw runtime/_sample/detail_raw

  # 没有 list_raw 时，可从已保存的列表页 HTML 现生成（回归用）
  python run_clean.py --date 2026-11-01 --list-html runtime/samples/x.html \
      --list-ts 20261101_0900 --detail-raw runtime/_sample/detail_raw

流程（顺序不能换）：
  读 list -> 清洗去重 -> 读 detail -> 清洗去重 -> 合并 item
  -> 红黄绿分级（红行剔除）-> 落盘 -> 报表

不做：入库、登录、画布、详情采集。人工核对看 日报_<date>.xlsx。
"""

import argparse
import datetime
import importlib.util
import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import clean_detail
import clean_list
import clean_merge
import export
import report
import rules

DEFAULT_ROOT = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\runtime"
DEFAULT_CONFIG = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\config\targets.json"
LIST_MODULE_DIR = os.path.join(os.path.dirname(_MODULE_DIR), "1.列表页采集")


def _log(msg):
    print(msg)
    sys.stdout.flush()


# ------------------------------------------------------------
# 从 HTML 现生成 list_raw（回归 / 补跑）
# ------------------------------------------------------------
def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def generate_list_raw(html_path, ts, root, targets_config=None):
    """parse_list + filter_product -> list_raw/<关键词>/<ts>.jsonl，返回文件路径。

    targets_config 是采集目标配置（targets.json），**不是** --config 的清洗阈值；
    两者混用会让关键词/价格过滤静默失效（见 2026-11-09 修复）。

    产出与 collect_list 保持一致：只写通过过滤的行（落盘契约见
    docs/列表页采集-待办清单 L-05，清洗层对缺 passed 的行视为通过）。
    """
    parse_list = _load_module("parse_list", os.path.join(LIST_MODULE_DIR, "parse_list.py"))
    filter_product = _load_module(
        "filter_product", os.path.join(LIST_MODULE_DIR, "filter_product.py"))

    cfg = targets_config or DEFAULT_CONFIG
    ruleset = filter_product.load_rules(cfg)
    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        rows = parse_list.parse_list(f.read())
    passed = filter_product.filter(rows, cfg)

    out_dir = export.ensure_dir(os.path.join(root, "list_raw", ruleset["keyword"]))
    out_path = os.path.join(out_dir, ts + ".jsonl")
    export.write_jsonl(out_path, passed)
    _log("[清洗] 由 HTML 生成 list_raw：%s（解析 %d 行，通过 %d 行）"
         % (out_path, len(rows), len(passed)))
    return out_path


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def run(args):
    cfg = rules.load_config(args.get("config"))
    targets_config = args.get("targets_config") or DEFAULT_CONFIG
    root = args.get("root") or DEFAULT_ROOT
    date = args.get("date") or rules.today_str()
    # 目录按用户口径用 YYYYMMDD；行内 crawl_date 仍是 YYYY-MM-DD
    out_dir = args.get("out") or os.path.join(root, "clean", date.replace("-", ""))
    export.ensure_dir(out_dir)

    # 0) 可选的 list_raw 现生成（多个 HTML -> 多轮，用来验证同日去重）
    # 画布整链路调用时不必传路径：缺省读本轮 runtime 下的 list_raw / detail_raw。
    list_paths = list(args.get("list_raw") or [os.path.join(root, "list_raw")])
    htmls = args.get("list_html") or []
    if isinstance(htmls, str):
        htmls = [htmls] if htmls else []
    tss = args.get("list_ts") or []
    if isinstance(tss, str):
        tss = [tss] if tss else []
    for i, html_path in enumerate(htmls):
        ts = tss[i] if i < len(tss) and tss[i] else \
            datetime.datetime.now().strftime("%Y%m%d_%H%M")
        list_paths.append(generate_list_raw(html_path, ts, root, targets_config))

    # 1) 列表
    lst = clean_list.clean_files([p for p in list_paths if p], date=date)
    _log("[清洗] 列表：原始 %(raw_rows)d -> 去重 %(deduped)d -> 通过 %(passed)d / 过滤 %(filtered)d"
         % lst["stats"])

    # 2) 详情
    detail_paths = list(args.get("detail_raw") or [os.path.join(root, "detail_raw")])
    det = clean_detail.clean_files([p for p in detail_paths if p], date=date)
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
    report_path = report.save(date, qres["items"], qres["skus"], qres["inventory"],
                              qres["anomalies"], out_dir, qstats, extra)

    meta = {
        "date": date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "out_dir": out_dir,
        "args": {k: v for k, v in args.items() if k != "cfg"},
        "counts": qstats,
        "files": {"list": lst["stats"]["files"], "detail": det["stats"]["files"]},
        "outputs": [report_path] + [
            os.path.join(out_dir, n) for n in
            ("item.jsonl", "item.xlsx", "sku.jsonl", "sku.xlsx",
             "inventory.jsonl", "anomalies.jsonl")],
    }
    export.write_json(os.path.join(out_dir, "run_meta.json"), meta)

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
