"""
============================================================
④ 数据入库 — 商品表（competitor_product）
============================================================
作用：读 product_clean Excel → 提取商品级字段去重 → upsert MySQL

输入：product_clean/ 下的 13 列清洗 Excel（有表头）
输出：MySQL competitor_product（按 product_id upsert）

调用方式（影刀）：
  product_ingest.main("清洗Excel路径", "database.json路径")
============================================================
"""

import json
import os
import sys
from datetime import date

import openpyxl
import pymysql

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULES_DIR = os.path.dirname(_MODULE_DIR)
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)


# ============================================================
# 数据库
# ============================================================

def _load_db_config(config_path: str) -> dict:
    path = os.path.normpath(os.path.abspath(
        str(config_path).strip().strip("\"'")))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到 database.json: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _connect_db(config_path: str):
    cfg = _load_db_config(config_path)
    return pymysql.connect(
        host=cfg.get("host", "127.0.0.1"),
        port=cfg.get("port", 3306),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
    )


def _parse_int(raw) -> int:
    if raw is None:
        return 0
    try:
        return int(float(str(raw).strip()))
    except Exception:
        return 0


SQL_UPSERT = """
    INSERT INTO competitor_product
        (product_id, product_name, shop_name, main_image_url,
         detail_url, sales, first_crawl_date, latest_crawl_date)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        product_name     = VALUES(product_name),
        shop_name        = VALUES(shop_name),
        main_image_url   = VALUES(main_image_url),
        detail_url       = VALUES(detail_url),
        sales            = VALUES(sales),
        latest_crawl_date = VALUES(latest_crawl_date)
"""


# ============================================================
# 主流程
# ============================================================

def ingest(cleaned_path: str, config_path: str) -> dict:
    """读清洗 Excel → 商品去重入库"""
    cleaned_path = os.path.normpath(os.path.abspath(
        str(cleaned_path).strip().strip("\"'")))

    wb = openpyxl.load_workbook(cleaned_path, read_only=True, data_only=True)
    ws = wb.active

    conn = _connect_db(config_path)
    cursor = conn.cursor()
    today = date.today()

    seen = set()
    inserted = 0
    skipped = 0

    try:
        conn.begin()

        # min_row=2：跳过表头
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue

            values = list(row)
            while len(values) < 13:
                values.append("")

            pid = str(values[0]).strip()
            if not pid:
                skipped += 1
                continue

            # 商品去重：同一 product_id 只入库一次
            if pid in seen:
                continue
            seen.add(pid)

            pname   = str(values[1] or "")[:512]
            shop    = str(values[2] or "")[:256]
            img     = str(values[3] or "")[:1024]
            sales   = _parse_int(values[10])

            cursor.execute(SQL_UPSERT, (
                pid, pname, shop, img,    # product_id, name, shop, main_image
                "",                       # detail_url — 新版无此字段，置空
                sales, today, today,
            ))
            inserted += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        wb.close()
        conn.close()

    return {"ok": True, "inserted": inserted, "skipped": skipped}


def _safe_path(p):
    if p is None:
        return None
    s = str(p)
    for i in range(1, 10):
        s = s.replace(chr(i), '\\' + str(i))
    s = s.replace('\r', '\\r')
    s = s.replace('\n', '\\n')
    s = s.replace('\f', '\\f')
    s = s.replace('\v', '\\v')
    return s


def main(cleaned_path: str, config_path: str) -> dict:
    """
    影刀入口
    cleaned_path = product_clean Excel 路径
    config_path  = database.json 路径
    """
    cleaned_path = _safe_path(cleaned_path)
    config_path = _safe_path(config_path)
    return ingest(cleaned_path, config_path)


if __name__ == "__main__":
    EXCEL = r"../../runtime/product_clean/demo.xlsx"
    CONFIG = r"../config/database.json"
    print(json.dumps(ingest(EXCEL, CONFIG), ensure_ascii=False, indent=2))
