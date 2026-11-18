# -*- coding: utf-8 -*-
"""N3.1 输入与读取：参数/日期/目录 + 可选的 list_html 现生成。"""

import datetime
import importlib.util
import os
import sys

import export
import paths
import rules

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
LIST_MODULE_DIR = os.path.join(os.path.dirname(_MODULE_DIR), "1.列表页采集")
if LIST_MODULE_DIR not in sys.path:
    sys.path.insert(0, LIST_MODULE_DIR)
DEFAULT_CONFIG = paths.config_path("targets.json")


def _log(msg):
    print(msg)
    sys.stdout.flush()


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def generate_list_raw(html_path, ts, root, targets_config=None):
    """parse_list + filters -> list_raw/<关键词>/<ts>.jsonl，返回文件路径。"""
    parse_list = _load_module("parse_list", os.path.join(LIST_MODULE_DIR, "parse_list.py"))
    filters_mod = _load_module("filters", os.path.join(LIST_MODULE_DIR, "filters.py"))

    cfg = targets_config or DEFAULT_CONFIG
    ruleset = filters_mod.load_rules(cfg)
    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        rows = parse_list.parse_list(f.read())
    passed = filters_mod.filter(rows, cfg)

    out_dir = export.ensure_dir(os.path.join(root, "list_raw", ruleset["keyword"]))
    out_path = os.path.join(out_dir, ts + ".jsonl")
    export.write_jsonl(out_path, passed)
    _log("[清洗] 由 HTML 生成 list_raw：%s（解析 %d 行，通过 %d 行）"
         % (out_path, len(rows), len(passed)))
    return out_path


def resolve(args, default_root):
    """解析输入：cfg / 日期 / 输出目录 / list_paths / detail_paths。"""
    args = args or {}
    cfg = rules.load_config(args.get("config"))
    targets_config = args.get("targets_config") or DEFAULT_CONFIG
    root = args.get("root") or default_root
    date = args.get("date") or rules.today_str()
    # 目录按用户口径用 YYYYMMDD；行内 crawl_date 仍是 YYYY-MM-DD
    out_dir = args.get("out") or os.path.join(root, "clean", date.replace("-", ""))
    export.ensure_dir(out_dir)

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

    detail_paths = list(args.get("detail_raw") or [os.path.join(root, "detail_raw")])
    return {
        "cfg": cfg, "targets_config": targets_config, "root": root,
        "date": date, "out_dir": out_dir,
        "list_paths": [p for p in list_paths if p],
        "detail_paths": [p for p in detail_paths if p],
    }


def main(args=None):
    return {"ok": True}
