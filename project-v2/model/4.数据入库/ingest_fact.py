"""事实入库：fact_item_price / fact_sku_price / fact_sku_inventory。

幂等：主键 (product_id|sku_id, crawl_date) + ON DUPLICATE KEY UPDATE。
同一天重跑，行数不变，只更新值与 batch_id；不追加重复快照。
价格用 Decimal（两位小数），None 保持 NULL —— 不拿 0 顶替。
"""

from decimal import Decimal

import datetime


def dec(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(round(float(v), 2)))
    except (TypeError, ValueError):
        return None


def to_date(v):
    s = str(v or "").strip()
    return datetime.date.fromisoformat(s[:10]) if s else None


def _bit(v):
    if v is None:
        return None
    return 1 if v else 0


ITEM_SQL = """
INSERT INTO fact_item_price
    (product_id, crawl_date, price, price_list, price_source, price_complete,
     item_price_scope, min_sku_price, max_sku_price, sku_count, priced_sku_count,
     sales, quality, review_status, is_late, batch_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    price            = VALUES(price),
    price_list       = VALUES(price_list),
    price_source     = VALUES(price_source),
    price_complete   = VALUES(price_complete),
    item_price_scope = VALUES(item_price_scope),
    min_sku_price    = VALUES(min_sku_price),
    max_sku_price    = VALUES(max_sku_price),
    sku_count        = VALUES(sku_count),
    priced_sku_count = VALUES(priced_sku_count),
    sales            = VALUES(sales),
    quality          = VALUES(quality),
    review_status    = VALUES(review_status),
    is_late          = VALUES(is_late),
    batch_id         = VALUES(batch_id)
"""

SKU_SQL = """
INSERT INTO fact_sku_price
    (sku_id, crawl_date, product_id, price, quantity, in_stock,
     price_complete, item_price, quality, review_status, is_late, batch_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    product_id     = VALUES(product_id),
    price          = VALUES(price),
    quantity       = VALUES(quantity),
    in_stock       = VALUES(in_stock),
    price_complete = VALUES(price_complete),
    item_price     = VALUES(item_price),
    quality        = VALUES(quality),
    review_status  = VALUES(review_status),
    is_late        = VALUES(is_late),
    batch_id       = VALUES(batch_id)
"""

INV_SQL = """
INSERT INTO fact_sku_inventory
    (sku_id, crawl_date, product_id, quantity, in_stock, reason, batch_id)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    product_id = VALUES(product_id),
    quantity   = VALUES(quantity),
    in_stock   = VALUES(in_stock),
    reason     = VALUES(reason),
    batch_id   = VALUES(batch_id)
"""


def upsert_item(conn, row, batch_id, is_late):
    # 趋势价优先详情；没有深采的商品保留列表价，但明确标 price_source='list'，
    # 趋势视图只取 detail（plan §2.4c 铁律 2）。
    price = row.get("price_detail")
    source = str(row.get("price_source") or "")
    if price is None and row.get("price_list") is not None:
        price = row.get("price_list")
        source = "list"
    with conn.cursor() as cur:
        cur.execute(ITEM_SQL, (
            row["product_id"], to_date(row["crawl_date"]),
            dec(price), dec(row.get("price_list")),
            source[:16],
            _bit(row.get("price_complete")),
            str(row.get("item_price_scope") or "")[:16],
            dec(row.get("min_sku_price")), dec(row.get("max_sku_price")),
            row.get("sku_count"), row.get("priced_sku_count"),
            row.get("sales"),
            str(row.get("quality") or "")[:8],
            str(row.get("review_status") or "")[:16],
            1 if is_late else 0, batch_id,
        ))


def upsert_sku(conn, row, batch_id, is_late):
    with conn.cursor() as cur:
        cur.execute(SKU_SQL, (
            row["sku_id"], to_date(row["crawl_date"]), row["product_id"],
            dec(row.get("price")), row.get("quantity"), _bit(row.get("in_stock")),
            _bit(row.get("price_complete")), dec(row.get("item_price")),
            str(row.get("quality") or "")[:8],
            str(row.get("review_status") or "")[:16],
            1 if is_late else 0, batch_id,
        ))


def upsert_inventory(conn, row, batch_id):
    with conn.cursor() as cur:
        cur.execute(INV_SQL, (
            row["sku_id"], to_date(row["crawl_date"]), row["product_id"],
            row.get("quantity"), _bit(row.get("in_stock")),
            str(row.get("reason") or "")[:32], batch_id,
        ))


def upsert_batch(conn, batch):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ingest_batch
                (batch_id, crawl_date, run_at, source_dir, item_rows, sku_rows,
                 inventory_rows, skipped_pending, skipped_rejected, skipped_no_key,
                 status, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                item_rows        = VALUES(item_rows),
                sku_rows         = VALUES(sku_rows),
                inventory_rows   = VALUES(inventory_rows),
                skipped_pending  = VALUES(skipped_pending),
                skipped_rejected = VALUES(skipped_rejected),
                skipped_no_key   = VALUES(skipped_no_key),
                status           = VALUES(status),
                note             = VALUES(note),
                source_dir       = VALUES(source_dir)
        """, (batch["batch_id"], to_date(batch["crawl_date"]), batch["run_at"],
              str(batch.get("source_dir") or "")[:512],
              batch.get("item_rows", 0), batch.get("sku_rows", 0),
              batch.get("inventory_rows", 0), batch.get("skipped_pending", 0),
              batch.get("skipped_rejected", 0), batch.get("skipped_no_key", 0),
              str(batch.get("status") or "running")[:16],
              str(batch.get("note") or "")[:512]))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("ingest_fact 由 run_ingest 调用；单元测试请用 --dry-run")
