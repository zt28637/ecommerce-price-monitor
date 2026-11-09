"""清洗产物的读写：列定义、JSONL / XLSX / JSON 原子写。

目录（runtime/clean/<YYYYMMDD>/）：
  item.xlsx / item.jsonl            商品·天，1 行
  sku.xlsx / sku.jsonl              SKU·天，有价行
  inventory.jsonl                   无价库存（不进行情表，仍保留事实）
  anomalies.jsonl                   所有丢弃 / 打标 / 过滤，不静默丢
  run_meta.json                     本次运行参数与产物清单
  日报_<date>.xlsx                   人工看的那份（概览 / 商品 / SKU / 库存 / 异常）

Excel 纪律：product_id / sku_id 一律按文本写（防科学计数法），价格 float 两位小数。
"""

import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ------------------------------------------------------------
# 列定义（顺序即 Excel 列序；三跳闸门要求列序固定）
# ------------------------------------------------------------
ITEM_COLUMNS = [
    ("crawl_date", "采集日期", 12),
    ("product_id", "商品ID", 16),
    ("merge_status", "合并状态", 12),
    ("title", "标题", 46),
    ("shop_name", "店铺", 16),
    ("price_list", "列表价", 10),
    ("price_list_raw", "列表价原文", 12),
    ("sales", "销量", 10),
    ("sales_raw", "销量原文", 14),
    ("sales_flag", "销量标记", 16),
    ("prov_city", "发货地", 12),
    ("main_image_url", "主图链接", 34),
    ("detail_url", "详情链接", 34),
    ("platform", "平台", 10),
    ("is_promoted", "推广位", 8),
    ("passed", "过滤通过", 9),
    ("filter_reason", "过滤原因", 12),
    ("price_detail", "详情价", 10),
    ("price_detail_raw", "详情价原文", 12),
    ("price_desc", "价格口径词", 10),
    ("item_price_scope", "价格口径", 10),
    ("hide_other_price", "隐藏其他价", 10),
    ("price_complete", "价格完整", 10),
    ("price_coverage", "价格覆盖", 10),
    ("sku_count", "SKU数", 8),
    ("priced_sku_count", "有价SKU", 8),
    ("min_sku_price", "最低SKU价", 11),
    ("max_sku_price", "最高SKU价", 11),
    ("flags", "质量标记", 28),
    ("quality", "质量", 8),
    ("review_status", "状态", 12),
    ("list_ts", "列表轮次", 14),
    ("detail_ts", "详情轮次", 14),
    ("source_files", "来源文件", 30),
]

SKU_COLUMNS = [
    ("crawl_date", "采集日期", 12),
    ("sku_id", "SKU ID", 18),
    ("product_id", "商品ID", 16),
    ("title", "商品标题", 40),
    ("prop_names", "规格名", 40),
    ("prop_path", "规格路径", 26),
    ("price", "SKU价", 10),
    ("price_raw", "价格原文", 10),
    ("quantity", "库存", 8),
    ("quantity_text", "库存文案", 12),
    ("in_stock", "有货", 8),
    ("price_complete", "价格完整", 10),
    ("item_price", "商品价", 10),
    ("item_price_scope", "价格口径", 10),
    ("flags", "质量标记", 24),
    ("source_flags", "上游标记", 18),
    ("quality", "质量", 8),
    ("review_status", "状态", 12),
    ("crawl_ts", "采集轮次", 14),
]

INVENTORY_COLUMNS = [
    ("crawl_date", "采集日期", 12),
    ("product_id", "商品ID", 16),
    ("sku_id", "SKU ID", 18),
    ("title", "商品标题", 40),
    ("prop_names", "规格名", 40),
    ("prop_path", "规格路径", 26),
    ("quantity", "库存", 8),
    ("quantity_text", "库存文案", 12),
    ("in_stock", "有货", 8),
    ("reason", "无价原因", 18),
    ("item_price", "商品价", 10),
    ("item_price_scope", "价格口径", 10),
    ("price_complete", "价格完整", 10),
    ("flags", "质量标记", 20),
    ("source_flags", "上游标记", 18),
    ("crawl_ts", "采集轮次", 14),
]

TEXT_COLUMNS = {"product_id", "sku_id", "crawl_date", "crawl_ts", "list_ts", "detail_ts"}
PRICE_COLUMNS = {"price_list", "price_detail", "min_sku_price", "max_sku_price",
                 "price", "item_price"}


# ------------------------------------------------------------
# 目录与 JSONL
# ------------------------------------------------------------
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def read_jsonl(path, skip_bad=True):
    """读 JSONL -> (rows, bad_count)。坏行计数，不静默吞掉。"""
    rows, bad = [], 0
    if not os.path.exists(path):
        return rows, bad
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
                if not skip_bad:
                    raise
    return rows, bad


def atomic_write_text(path, text):
    ensure_dir(os.path.dirname(path) or ".")
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)
    return path


def write_jsonl(path, rows):
    lines = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows or [])
    return atomic_write_text(path, lines)


def write_json(path, obj):
    return atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ------------------------------------------------------------
# Excel
# ------------------------------------------------------------
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_QUALITY_FILL = {
    "red": PatternFill("solid", fgColor="F8CBAD"),
    "yellow": PatternFill("solid", fgColor="FFE699"),
    "green": PatternFill("solid", fgColor="E2EFDA"),
}
_REVIEW_FILL = {
    "pending": PatternFill("solid", fgColor="FFF2CC"),
    "rejected": PatternFill("solid", fgColor="F8CBAD"),
    "approved": PatternFill("solid", fgColor="E2EFDA"),
}


def _cell_value(col, val):
    if val is None:
        return ""
    if isinstance(val, (list, tuple, set)):
        return ";".join(str(x) for x in val)
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    if col in TEXT_COLUMNS:
        return str(val)
    if col in PRICE_COLUMNS:
        return float(val)
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    return val


def write_sheet(ws, rows, columns):
    """写一张表：表头冻结、列宽、主键文本、价格两位小数、质量着色。"""
    keys = [c[0] for c in columns]
    for j, (_, title, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=j, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "A2"

    qi = keys.index("quality") + 1 if "quality" in keys else None
    ri = keys.index("review_status") + 1 if "review_status" in keys else None

    for i, row in enumerate(rows, start=2):
        for j, col in enumerate(keys, start=1):
            cell = ws.cell(row=i, column=j, value=_cell_value(col, row.get(col)))
            if col in TEXT_COLUMNS:
                cell.number_format = "@"
            elif col in PRICE_COLUMNS:
                cell.number_format = "0.00"
        if qi:
            q = row.get("quality")
            if q in _QUALITY_FILL:
                ws.cell(row=i, column=qi).fill = _QUALITY_FILL[q]
        if ri:
            s = row.get("review_status")
            if s in _REVIEW_FILL:
                ws.cell(row=i, column=ri).fill = _REVIEW_FILL[s]
    return ws


def write_xlsx(path, sheets):
    """sheets: [(sheet_name, rows, columns), ...]"""
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows, columns in sheets:
        ws = wb.create_sheet(title=name[:31])
        write_sheet(ws, rows or [], columns)
    ensure_dir(os.path.dirname(path) or ".")
    part = path + ".part"
    wb.save(part)
    os.replace(part, path)
    return path


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
