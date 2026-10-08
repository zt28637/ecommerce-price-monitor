"""
============================================================
④ 数据入库 — SKU表 + 价格历史（competitor_sku + price_history）
============================================================
作用：读 product_clean Excel → SKU 逐行 upsert + 价格历史 append

输入：product_clean/ 下的 13 列清洗 Excel（有表头）
  → competitor_sku：按 (product_id, sku_name) upsert 三档价格
  → price_history：每次采集追加一条（append only）

调用方式（影刀）：
  sku_ingest.main("清洗Excel路径", "database.json路径")
============================================================
"""

import json
import os
import sys
from datetime import date, datetime

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


def _to_decimal(raw) -> object:
    """价格字符串 → Decimal 或 None"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in ("?", "null", "None"):
        return None
    try:
        return round(float(text), 2)
    except Exception:
        return None


def _parse_date(raw, fallback=None) -> date:
    """采集时间 → date 对象"""
    text = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    # 尝试 ISO 格式 "2026-07-25 13:00:00"
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").date()
    except Exception:
        pass
    return fallback or date.today()


def _parse_datetime(raw) -> datetime:
    """采集时间 → datetime 对象"""
    text = str(raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y/%m/%d %H:%M:%S", "%Y年%m月%d日%H时%M分"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return datetime.now()


SQL_SKU_UPSERT = """
    INSERT INTO competitor_sku
        (product_id, sku_name, sku_id, sku_image_url,
         sku_price, original_price, activity_price, crawl_time)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        sku_id          = VALUES(sku_id),
        sku_image_url   = VALUES(sku_image_url),
        sku_price       = VALUES(sku_price),
        original_price  = VALUES(original_price),
        activity_price  = VALUES(activity_price),
        crawl_time      = VALUES(crawl_time)
"""

SQL_HISTORY_INSERT = """
    INSERT INTO price_history
        (product_id, sku_name, sku_id, price, crawl_date, crawl_time)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


# ============================================================
# 主流程
# ============================================================

def ingest(cleaned_path: str, config_path: str) -> dict:
    """读清洗 Excel → SKU 逐行入库"""
    cleaned_path = os.path.normpath(os.path.abspath(
        str(cleaned_path).strip().strip("\"'")))

    wb = openpyxl.load_workbook(cleaned_path, read_only=True, data_only=True)
    ws = wb.active

    conn = _connect_db(config_path)
    cursor = conn.cursor()

    sku_inserted = 0
    history_inserted = 0
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

            pid    = str(values[0]).strip()
            sname  = str(values[5] or "").strip()[:256]
            sid    = str(values[4] or "").strip()[:32]
            simg   = str(values[6] or "").strip()[:1024]
            sprice = _to_decimal(values[7])
            orig   = _to_decimal(values[8])
            actv   = _to_decimal(values[9])
            ctime  = _parse_datetime(values[11])
            cdate  = _parse_date(values[11])

            # 过滤：商品ID 或 SKU名称 为空 → 跳过
            if not pid or not sname:
                skipped += 1
                continue

            # 过滤：实际售价为空 → 跳过
            if sprice is None:
                skipped += 1
                continue

            # ── competitor_sku upsert ──
            cursor.execute(SQL_SKU_UPSERT, (
                pid, sname, sid, simg, sprice, orig, actv, ctime,
            ))
            sku_inserted += 1

            # ── price_history append ──
            cursor.execute(SQL_HISTORY_INSERT, (
                pid, sname, sid, sprice, cdate, ctime,
            ))
            history_inserted += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        wb.close()
        conn.close()

    return {
        "ok": True,
        "sku_inserted": sku_inserted,
        "history_inserted": history_inserted,
        "skipped": skipped,
    }


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
