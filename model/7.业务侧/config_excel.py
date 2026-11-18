# -*- coding: utf-8 -*-
"""Excel 配置入口：监控关键词.xlsx → 校验 → config/targets.json。

业务侧只让运营改这一张表；本模块负责把表翻译成现有 N1/N3 能读的 JSON。
不改 N1 的读取逻辑，也不引入新的配置格式。
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = os.path.dirname(_HERE)
_TOOL = os.path.join(_MODEL, "tool")
if _TOOL not in sys.path:
    sys.path.insert(0, _TOOL)

import paths

try:
    from openpyxl import Workbook, load_workbook
except ImportError:          # 离线环境给明确提示
    Workbook = None
    load_workbook = None

COLUMNS = ["启用", "名称", "关键词", "最低价", "最高价", "包含词", "排除词",
           "最多翻页数", "目标数量", "排序", "备注"]
REQUIRED = {"名称", "关键词"}
DEFAULT_COLLECT = {"max_pages": 5, "target_n": 50, "sort": "sale"}
DEFAULT_DEFAULTS = {"min_price": 0, "max_price": 0, "include": [], "exclude": [],
                    "collect": dict(DEFAULT_COLLECT)}
TRUE_WORDS = {"1", "true", "yes", "y", "是", "开", "启用", "✓", "√", "on"}


# ---------- 单元格归一 ----------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "".join(_text(x.get("text") if isinstance(x, dict) else x) for x in v)
    if isinstance(v, dict):
        return _text(v.get("text") or v.get("name") or "")
    return str(v).strip()


def _bool(v):
    if isinstance(v, bool):
        return v
    return _text(v).lower() in TRUE_WORDS


def _num(v, default=0.0):
    s = _text(v)
    if not s:
        return float(default)
    s = s.replace("¥", "").replace("￥", "").replace(",", "").replace("，", "")
    try:
        return float(s)
    except ValueError:
        raise ValueError("不是数字：%s" % _text(v))


def _int(v, default=0):
    return int(_num(v, default))


def _split(v):
    s = _text(v)
    if not s:
        return []
    out, seen = [], set()
    for part in re.split(r"[,，、\n\r;；]+", s):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


# ---------- 读表 ----------

def read_rows(path):
    if load_workbook is None:
        raise RuntimeError("openpyxl 未安装：pip install openpyxl")
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        raise ValueError("Excel 为空")
    header = [_text(c) for c in rows[0]]
    idx = {name: i for i, name in enumerate(header) if name}
    missing = [c for c in REQUIRED if c not in idx]
    if missing:
        raise ValueError("缺少列：%s" % "、".join(missing))
    out = []
    for rownum, row in enumerate(rows[1:], start=2):
        if all(_text(c) == "" for c in row):
            continue
        rec = {name: (row[i] if i < len(row) else None) for name, i in idx.items()}
        rec["_row"] = rownum
        out.append(rec)
    return out


# ---------- 校验 / 构建 ----------

def build_targets(rows, defaults=None):
    """返回 (targets, errors)。只校验「启用」行；未启用行直接跳过。"""
    defaults = defaults or DEFAULT_DEFAULTS
    collect_defaults = dict(DEFAULT_COLLECT)
    collect_defaults.update((defaults.get("collect") or {}))
    targets, errors = [], []
    for rec in rows:
        if not _bool(rec.get("启用")):
            continue
        row = rec.get("_row")
        name = _text(rec.get("名称"))
        keyword = _text(rec.get("关键词"))
        errs = []
        if not name:
            errs.append("名称为空")
        if not keyword:
            errs.append("关键词为空")
        try:
            min_price = _num(rec.get("最低价"), 0.0)
        except ValueError as e:
            errs.append("最低价：%s" % e)
            min_price = 0.0
        try:
            max_price = _num(rec.get("最高价"), 0.0)
        except ValueError as e:
            errs.append("最高价：%s" % e)
            max_price = 0.0
        if min_price < 0 or max_price < 0:
            errs.append("价格不能为负")
        if min_price and max_price and min_price > max_price:
            errs.append("最低价大于最高价")
        try:
            max_pages = _int(rec.get("最多翻页数"), collect_defaults["max_pages"])
        except ValueError as e:
            errs.append("最多翻页数：%s" % e)
            max_pages = collect_defaults["max_pages"]
        try:
            target_n = _int(rec.get("目标数量"), collect_defaults["target_n"])
        except ValueError as e:
            errs.append("目标数量：%s" % e)
            target_n = collect_defaults["target_n"]
        if max_pages < 1:
            errs.append("最多翻页数必须≥1")
        if target_n < 0:
            errs.append("目标数量不能为负")
        sort = _text(rec.get("排序")) or "销量"
        if sort not in ("销量", "sale"):
            errs.append("排序只支持销量")
        if errs:
            errors.append({"row": row, "name": name or "第%s行" % row, "errors": errs})
            continue
        targets.append({
            "name": name, "keyword": keyword,
            "min_price": min_price, "max_price": max_price,
            "include": _split(rec.get("包含词")),
            "exclude": _split(rec.get("排除词")),
            "collect": {"max_pages": max_pages, "target_n": target_n,
                        "sort": "sale"},
        })
    if not rows:
        errors.append({"row": 0, "name": "", "errors": ["Excel 没有数据行"]})
    elif not targets and not errors:
        errors.append({"row": 0, "name": "", "errors": ["没有启用的监控关键词"]})
    elif len(targets) > 1:
        # 2026-11-17 定：默认单目标。N1 只读 targets[0]，多行启用会静默丢配置，
        # 所以在配置入口直接报错，而不是让第 2 行起悄悄不跑。
        errors.append({"row": 0, "name": "", "errors": [
            "当前版本只支持单目标：启用了 %d 行（%s），请只保留一行"
            % (len(targets), "、".join(t["name"] for t in targets))]})
    return targets, errors


# ---------- 落盘 ----------

def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        backup_dir = os.path.join(paths.RUNTIME, "config_backup")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.splitext(os.path.basename(path))[0]
        shutil.copy2(path, os.path.join(backup_dir, "%s_%s.json" % (base, ts)))
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)


def sync(excel_path, out_path=None, check=False):
    """Excel → targets.json。check=True 只校验，不写文件。"""
    out_path = out_path or paths.config_path("targets.json")
    if not os.path.isabs(excel_path):
        excel_path = os.path.join(paths.PROJECT, excel_path)
    if not os.path.isabs(out_path):
        out_path = os.path.join(paths.PROJECT, out_path)
    rows = read_rows(excel_path)
    base = _load_json(out_path)
    defaults = base.get("defaults") or dict(DEFAULT_DEFAULTS)
    targets, errors = build_targets(rows, defaults)
    if errors:
        return {"ok": False, "count": 0, "errors": errors,
                "path": out_path, "excel": excel_path}
    if check:
        return {"ok": True, "count": len(targets), "errors": [],
                "path": out_path, "excel": excel_path, "targets": targets}
    _write_json_atomic(out_path, {"defaults": defaults, "targets": targets})
    return {"ok": True, "count": len(targets), "errors": [],
            "path": out_path, "excel": excel_path, "targets": targets}


def create_sample(path, source_json=None, force=False):
    """生成一份可编辑的示例表；已存在且 force=False 时不覆盖。

    优先从现有 targets.json 的第一条 target 生成，保证示例与真实配置一致。
    """
    if Workbook is None:
        raise RuntimeError("openpyxl 未安装：pip install openpyxl")
    if os.path.exists(path) and not force:
        return {"ok": True, "path": path, "created": False}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = ["是", "枕头", "护颈枕", 20, 1500, "护颈,颈椎",
           "汽车,车载,靠垫", 3, 60, "销量", "示例"]
    src = _load_json(source_json or paths.config_path("targets.json"))
    targets = src.get("targets") or []
    if targets:
        t = targets[0]
        c = t.get("collect") or {}
        row = ["是", t.get("name", ""), t.get("keyword", ""),
               t.get("min_price", 0), t.get("max_price", 0),
               ",".join(t.get("include") or []), ",".join(t.get("exclude") or []),
               c.get("max_pages", 5), c.get("target_n", 50),
               "销量", t.get("name", "示例")]
    wb = Workbook()
    ws = wb.active
    ws.title = "监控关键词"
    ws.append(COLUMNS)
    ws.append(row)
    widths = [8, 14, 16, 10, 10, 18, 30, 10, 10, 10, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(path)
    return {"ok": True, "path": path, "created": True}


def main(args=None):
    ap = argparse.ArgumentParser(description="Excel 配置 → targets.json")
    ap.add_argument("--excel", default="config/监控关键词.xlsx")
    ap.add_argument("--out", default="")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--init-sample", action="store_true", help="生成示例 Excel")
    ap.add_argument("--force", action="store_true", help="示例表已存在时覆盖")
    a = vars(ap.parse_args(args))
    if a["init_sample"]:
        res = create_sample(a["excel"] if os.path.isabs(a["excel"])
                            else os.path.join(paths.PROJECT, a["excel"]),
                            force=a["force"])
    else:
        try:
            res = sync(a["excel"], a["out"] or None, check=a["check"])
        except Exception as e:
            res = {"ok": False, "errors": [{"row": 0, "name": "", "errors": [str(e)]}]}
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
