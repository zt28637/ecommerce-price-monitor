-- ============================================================
-- BI 看板视图（Metabase 等 BI 工具专用）
-- 目的：把三张规范表拼成可直接拖拽的宽表，看板里不必再写复杂 SQL
-- 执行：mysql -u root -p < init_bi_views.sql
-- 依赖：init_database_v0.sql（MySQL 8.0+，用到窗口函数 ROW_NUMBER/LAG）
-- ============================================================

USE price_monitor;

-- ============================================================
-- 1. v_price_daily — 价格日快照（宽表）
--
-- 【重要】price_history 是 append-only，每跑一次采集就追加一批，
-- 同一 (product_id, sku_name, crawl_date) 可能有多条（实测最多 32 条）。
-- 直接用它画趋势会重复计数，因此这里按 crawl_time 取当日最后一次作为当日价。
-- 看板的折线图/对比图一律用本视图，不要直接连 price_history。
-- ============================================================
CREATE OR REPLACE VIEW v_price_daily AS
SELECT
    product_id,
    product_name,
    shop_name,
    sku_name,
    sku_id,
    crawl_date,
    crawl_time,
    price,
    sales
FROM (
    SELECT
        h.product_id,
        p.product_name,
        p.shop_name,
        h.sku_name,
        h.sku_id,
        h.crawl_date,
        h.crawl_time,
        h.price,
        p.sales,
        ROW_NUMBER() OVER (
            PARTITION BY h.product_id, h.sku_name, h.crawl_date
            ORDER BY h.crawl_time DESC, h.id DESC
        ) AS rn
    FROM price_history h
    JOIN competitor_product p ON p.product_id = h.product_id
) t
WHERE rn = 1;

-- ============================================================
-- 2. v_price_change — 价格变动（带昨日价 / 历史最低 / 涨跌幅）
-- 直接用于「降价榜」「涨价预警」看板，Metabase 里筛 price_diff < 0 即可
-- ============================================================
CREATE OR REPLACE VIEW v_price_change AS
SELECT
    product_id,
    product_name,
    shop_name,
    sku_name,
    crawl_date,
    price,
    LAG(price) OVER (PARTITION BY product_id, sku_name ORDER BY crawl_date) AS prev_price,
    price - LAG(price) OVER (PARTITION BY product_id, sku_name ORDER BY crawl_date) AS price_diff,
    ROUND(
        (price - LAG(price) OVER (PARTITION BY product_id, sku_name ORDER BY crawl_date))
        / NULLIF(LAG(price) OVER (PARTITION BY product_id, sku_name ORDER BY crawl_date), 0) * 100,
        2
    ) AS change_pct,
    MIN(price) OVER (PARTITION BY product_id, sku_name) AS min_price,
    MAX(price) OVER (PARTITION BY product_id, sku_name) AS max_price,
    -- 不含当日的历史最低价 / 最高价：口径与 alert.py 的「历史新低」预警一致
    MIN(price) OVER (
        PARTITION BY product_id, sku_name ORDER BY crawl_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS min_price_before,
    MAX(price) OVER (
        PARTITION BY product_id, sku_name ORDER BY crawl_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS max_price_before
FROM v_price_daily;

-- ============================================================
-- 3. v_sku_latest — SKU 当前快照（三档价格 + 折扣率）
-- 用于商品明细表、价格分布、折扣力度分析
-- ============================================================
CREATE OR REPLACE VIEW v_sku_latest AS
SELECT
    s.product_id,
    p.product_name,
    p.shop_name,
    s.sku_name,
    s.sku_id,
    s.sku_price,
    s.original_price,
    s.activity_price,
    ROUND(s.sku_price / NULLIF(s.original_price, 0) * 10, 1) AS discount_rate,
    s.crawl_time,
    p.sales,
    p.detail_url,
    p.main_image_url
FROM competitor_sku s
JOIN competitor_product p ON p.product_id = s.product_id;

-- ============================================================
-- 4. v_shop_summary — 店铺维度汇总
-- 用于店铺对比、竞品格局概览
-- ============================================================
CREATE OR REPLACE VIEW v_shop_summary AS
SELECT
    p.shop_name,
    COUNT(DISTINCT p.product_id)              AS product_count,
    COUNT(DISTINCT s.sku_name)                AS sku_count,
    ROUND(AVG(s.sku_price), 2)                AS avg_price,
    MIN(s.sku_price)                          AS min_price,
    MAX(s.sku_price)                          AS max_price,
    SUM(p.sales)                              AS total_sales
FROM competitor_product p
LEFT JOIN competitor_sku s ON s.product_id = p.product_id
GROUP BY p.shop_name;

-- ============================================================
-- 5. 验证
-- ============================================================
SELECT 'BI 视图创建完成' AS status;
SELECT TABLE_NAME AS view_name FROM information_schema.VIEWS
WHERE TABLE_SCHEMA = 'price_monitor' ORDER BY TABLE_NAME;

-- 校验：去重后与原始行数对比（应远小于 819）
SELECT
    (SELECT COUNT(*) FROM price_history) AS raw_rows,
    (SELECT COUNT(*) FROM v_price_daily) AS deduped_rows;