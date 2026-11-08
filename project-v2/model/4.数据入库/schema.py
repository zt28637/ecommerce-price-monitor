"""v2 星型模型：建库 / 建表 / 建视图。

与 v1 的 competitor_* / price_history 完全隔离，只新增对象，不改旧表。
计划 §5.1：

  dim_product       维度 · product_id        SCD2：改标题/改店铺/换平台留版本
  dim_sku           维度 · sku_id            规格组合名
  fact_item_price   事实 · (product_id, 采集日期)  商品级（详情价 + 列表价分列）
  fact_sku_price    事实 · (sku_id, 采集日期)      SKU 精确价 + 库存 + price_complete
  fact_sku_inventory 事实 · (sku_id, 采集日期)     无价库存（v2 扩展；不参与价格趋势）
  ingest_batch      台账 · batch_id          每批一行，counts 与来源目录

口径（plan §5.2 / 5.3）：
  · 主键用「采集日期」，不用写入时间
  · 缺口不插值：缺哪天空哪天
  · 趋势只认 price_complete=1 且 review_status ∈ (auto_pass, approved)
"""

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import db

TABLES = {
    "dim_product": """
CREATE TABLE IF NOT EXISTS dim_product (
    product_id      VARCHAR(32)  NOT NULL COMMENT '淘宝商品ID',
    version_no      INT          NOT NULL DEFAULT 1 COMMENT '版本号（同商品内递增）',
    title           VARCHAR(512) NOT NULL DEFAULT '' COMMENT '标题（该版本期间）',
    shop_name       VARCHAR(256) NOT NULL DEFAULT '' COMMENT '店铺',
    platform        VARCHAR(16)  NOT NULL DEFAULT '' COMMENT 'taobao/tmall/unknown',
    valid_from      DATE         NOT NULL COMMENT '该属性生效日（含）',
    valid_to        DATE         NULL     COMMENT '失效日（含）；NULL=当前版本',
    is_current      TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=当前版本',
    first_seen_date DATE         NOT NULL COMMENT '商品首次出现',
    last_seen_date  DATE         NOT NULL COMMENT '该版本最近被观测到',
    PRIMARY KEY (product_id, version_no),
    KEY idx_current (product_id, is_current),
    KEY idx_valid (valid_from, valid_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品维度（SCD2）'
""",
    "dim_sku": """
CREATE TABLE IF NOT EXISTS dim_sku (
    sku_id          VARCHAR(48)  NOT NULL COMMENT 'SKU ID；单规格为 <product_id>__default',
    product_id      VARCHAR(32)  NOT NULL COMMENT '所属商品',
    prop_names      VARCHAR(512) NOT NULL DEFAULT '' COMMENT '规格名，如 颜色:蓝;套餐:8新',
    prop_path       VARCHAR(512) NOT NULL DEFAULT '' COMMENT '原始 propPath',
    first_seen_date DATE         NOT NULL,
    last_seen_date  DATE         NOT NULL,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sku_id),
    KEY idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SKU 维度'
""",
    "fact_item_price": """
CREATE TABLE IF NOT EXISTS fact_item_price (
    product_id       VARCHAR(32)  NOT NULL,
    crawl_date       DATE         NOT NULL,
    price            DECIMAL(10,2) NULL COMMENT '详情价（趋势价，price_detail）',
    price_list       DECIMAL(10,2) NULL COMMENT '列表价（仅触发器，不进趋势）',
    price_source     VARCHAR(16)  NOT NULL DEFAULT '' COMMENT '趋势价来源，detail',
    price_complete   TINYINT(1)   NULL COMMENT '0=部分 SKU 有价',
    item_price_scope VARCHAR(16)  NOT NULL DEFAULT '' COMMENT 'min/default/unknown',
    min_sku_price    DECIMAL(10,2) NULL,
    max_sku_price    DECIMAL(10,2) NULL,
    sku_count        INT          NULL,
    priced_sku_count INT          NULL,
    sales            INT          NULL COMMENT '归一后销量；NULL=文案/缺失',
    quality          VARCHAR(8)   NOT NULL DEFAULT '' COMMENT 'green/yellow',
    review_status    VARCHAR(16)  NOT NULL DEFAULT '' COMMENT 'auto_pass/approved',
    is_late          TINYINT(1)   NOT NULL DEFAULT 0,
    batch_id         VARCHAR(48)  NOT NULL DEFAULT '',
    ingested_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id, crawl_date),
    KEY idx_date (crawl_date),
    KEY idx_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品级价格事实'
""",
    "fact_sku_price": """
CREATE TABLE IF NOT EXISTS fact_sku_price (
    sku_id         VARCHAR(48)  NOT NULL,
    crawl_date     DATE         NOT NULL,
    product_id     VARCHAR(32)  NOT NULL,
    price          DECIMAL(10,2) NOT NULL COMMENT 'SKU 精确价',
    quantity       INT          NULL COMMENT '库存数；NULL=页面未给',
    in_stock       TINYINT(1)   NULL,
    price_complete TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '所属商品价是否完整',
    item_price     DECIMAL(10,2) NULL COMMENT '同商品起售价，便于对照',
    quality        VARCHAR(8)   NOT NULL DEFAULT '',
    review_status  VARCHAR(16)  NOT NULL DEFAULT '',
    is_late        TINYINT(1)   NOT NULL DEFAULT 0,
    batch_id       VARCHAR(48)  NOT NULL DEFAULT '',
    ingested_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sku_id, crawl_date),
    KEY idx_product_date (product_id, crawl_date),
    KEY idx_date (crawl_date),
    KEY idx_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SKU 价格事实'
""",
    "fact_sku_inventory": """
CREATE TABLE IF NOT EXISTS fact_sku_inventory (
    sku_id      VARCHAR(48) NOT NULL,
    crawl_date  DATE        NOT NULL,
    product_id  VARCHAR(32) NOT NULL,
    quantity    INT         NULL,
    in_stock    TINYINT(1)  NULL,
    reason      VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'partial_sku_price/masked/price_null',
    batch_id    VARCHAR(48) NOT NULL DEFAULT '',
    ingested_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (sku_id, crawl_date),
    KEY idx_product_date (product_id, crawl_date),
    KEY idx_date (crawl_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='无价 SKU 库存事实（不进价格趋势）'
""",
    "ingest_batch": """
CREATE TABLE IF NOT EXISTS ingest_batch (
    batch_id            VARCHAR(48)  NOT NULL,
    crawl_date          DATE         NOT NULL,
    run_at              DATETIME     NOT NULL,
    source_dir          VARCHAR(512) NOT NULL DEFAULT '',
    item_rows           INT          NOT NULL DEFAULT 0,
    sku_rows            INT          NOT NULL DEFAULT 0,
    inventory_rows      INT          NOT NULL DEFAULT 0,
    skipped_pending     INT          NOT NULL DEFAULT 0,
    skipped_rejected    INT          NOT NULL DEFAULT 0,
    skipped_no_key      INT          NOT NULL DEFAULT 0,
    status              VARCHAR(16)  NOT NULL DEFAULT 'running',
    note                VARCHAR(512) NOT NULL DEFAULT '',
    PRIMARY KEY (batch_id),
    KEY idx_date (crawl_date),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='入库台账'
""",
}

VIEWS = {
    "v2_product_current": """
CREATE OR REPLACE VIEW v2_product_current AS
SELECT product_id, version_no, title, shop_name, platform,
       valid_from, first_seen_date, last_seen_date
FROM dim_product
WHERE is_current = 1
""",
    "v2_sku_latest": """
CREATE OR REPLACE VIEW v2_sku_latest AS
SELECT f.sku_id, f.product_id, d.prop_names, f.crawl_date, f.price,
       f.quantity, f.in_stock, f.price_complete, f.review_status
FROM fact_sku_price f
JOIN dim_sku d ON d.sku_id = f.sku_id
JOIN (
    SELECT sku_id, MAX(crawl_date) AS max_date
    FROM fact_sku_price
    GROUP BY sku_id
) m ON m.sku_id = f.sku_id AND m.max_date = f.crawl_date
""",
    # 行级趋势：上一有效价 / 差额 / 涨幅 / 不含当日历史最低 / 连续下跌天数
    "v2_sku_change": """
CREATE OR REPLACE VIEW v2_sku_change AS
WITH base AS (
    SELECT sku_id, product_id, crawl_date, price, quantity, in_stock,
           LAG(price) OVER (PARTITION BY sku_id ORDER BY crawl_date) AS prev_price,
           LAG(crawl_date) OVER (PARTITION BY sku_id ORDER BY crawl_date) AS prev_date
    FROM fact_sku_price
    WHERE price IS NOT NULL
      AND price_complete = 1
      AND review_status IN ('auto_pass', 'approved')
),
flags AS (
    SELECT base.*,
           CASE WHEN prev_price IS NOT NULL AND price < prev_price THEN 1 ELSE 0 END AS is_down
    FROM base
),
islands AS (
    SELECT flags.*,
           SUM(CASE WHEN is_down = 0 THEN 1 ELSE 0 END)
               OVER (PARTITION BY sku_id ORDER BY crawl_date
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS island
    FROM flags
),
streaks AS (
    SELECT islands.*,
           CASE WHEN is_down = 1 THEN
                ROW_NUMBER() OVER (PARTITION BY sku_id, island ORDER BY crawl_date)
           ELSE 0 END AS down_streak
    FROM islands
)
SELECT sku_id, product_id, crawl_date, price, quantity, in_stock,
       prev_date, prev_price,
       ROUND(price - prev_price, 2) AS price_diff,
       ROUND((price - prev_price) / NULLIF(prev_price, 0) * 100, 2) AS change_pct,
       MIN(price) OVER (PARTITION BY sku_id ORDER BY crawl_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS min_before,
       down_streak
FROM streaks
""",
    "v2_item_change": """
CREATE OR REPLACE VIEW v2_item_change AS
WITH base AS (
    SELECT product_id, crawl_date, price, price_list, price_complete, item_price_scope,
           LAG(price) OVER (PARTITION BY product_id ORDER BY crawl_date) AS prev_price,
           LAG(crawl_date) OVER (PARTITION BY product_id ORDER BY crawl_date) AS prev_date
    FROM fact_item_price
    WHERE price IS NOT NULL
      AND price_source = 'detail'
      AND review_status IN ('auto_pass', 'approved')
),
flags AS (
    SELECT base.*,
           CASE WHEN prev_price IS NOT NULL AND price < prev_price THEN 1 ELSE 0 END AS is_down
    FROM base
),
islands AS (
    SELECT flags.*,
           SUM(CASE WHEN is_down = 0 THEN 1 ELSE 0 END)
               OVER (PARTITION BY product_id ORDER BY crawl_date
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS island
    FROM flags
),
streaks AS (
    SELECT islands.*,
           CASE WHEN is_down = 1 THEN
                ROW_NUMBER() OVER (PARTITION BY product_id, island ORDER BY crawl_date)
           ELSE 0 END AS down_streak
    FROM islands
)
SELECT product_id, crawl_date, price, price_list, price_complete, item_price_scope,
       prev_date, prev_price,
       ROUND(price - prev_price, 2) AS price_diff,
       ROUND((price - prev_price) / NULLIF(prev_price, 0) * 100, 2) AS change_pct,
       MIN(price) OVER (PARTITION BY product_id ORDER BY crawl_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS min_before,
       down_streak
FROM streaks
""",
}


def ensure_database(config_path=None, database=None):
    """CREATE DATABASE IF NOT EXISTS；返回最终库名。"""
    cfg = db.load_config(config_path)
    name = database or cfg["database"]
    conn = db.connect_server(config_path)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `%s` "
                "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci" % name)
    finally:
        conn.close()
    return name


def ensure(conn, views=True):
    """建表 + 建视图（幂等）。返回 (tables, views)。"""
    with conn.cursor() as cur:
        for name, ddl in TABLES.items():
            cur.execute(ddl)
        if views:
            for name, ddl in VIEWS.items():
                cur.execute(ddl)
    return list(TABLES), list(VIEWS) if views else []


def main(args=None):
    args = args or {}
    name = ensure_database(args.get("config"), args.get("database"))
    conn = db.connect(args.get("config"), name)
    try:
        tables, views = ensure(conn, views=not args.get("no_views"))
        conn.commit()
        print("库：%s | 表 %s | 视图 %s" % (name, tables, views))
        return {"database": name, "tables": tables, "views": views}
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
