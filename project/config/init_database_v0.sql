-- ============================================================
-- V0 数据库初始化脚本（2026-07-21）
-- 竞品价格监控系统 · 三表：商品 / SKU快照 / 价格历史
-- 执行方式：mysql -u root -p < init_database_v0.sql
-- ============================================================

-- 1. 创建数据库
CREATE DATABASE IF NOT EXISTS price_monitor
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE price_monitor;

-- ============================================================
-- 2. 商品表（competitor_product）
-- 商品级信息，product_id 为业务唯一键
-- 写入：product_ingest.py — INSERT ON DUPLICATE KEY UPDATE
-- ============================================================
CREATE TABLE IF NOT EXISTS competitor_product (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY  COMMENT '自增主键',
    product_id       VARCHAR(32)   NOT NULL             COMMENT '淘宝商品ID（业务唯一键）',
    product_name     VARCHAR(512)  NOT NULL DEFAULT ''  COMMENT '商品标题',
    shop_name        VARCHAR(256)  NOT NULL DEFAULT ''  COMMENT '店铺名称',
    main_image_url   VARCHAR(1024) NOT NULL DEFAULT ''  COMMENT '商品主图URL',
    detail_url       VARCHAR(2048) NOT NULL DEFAULT ''  COMMENT '商品详情页链接（网页兜底用）',
    sales            INT           NOT NULL DEFAULT 0   COMMENT '商品级销量',
    first_crawl_date DATE          NOT NULL             COMMENT '首次采集日期',
    latest_crawl_date DATE         NOT NULL             COMMENT '最近采集日期',
    created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_product_id (product_id),
    INDEX idx_first_crawl (first_crawl_date),
    INDEX idx_latest_crawl (latest_crawl_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='竞品商品信息表';

-- ============================================================
-- 3. SKU 快照表（competitor_sku）
-- SKU 级价格快照；业务唯一键 (product_id, sku_name)
-- 写入：sku_ingest.py — INSERT ON DUPLICATE KEY UPDATE（三档价格全量覆盖）
-- ============================================================
CREATE TABLE IF NOT EXISTS competitor_sku (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY  COMMENT '自增主键',
    product_id       VARCHAR(32)   NOT NULL             COMMENT '商品ID',
    sku_name         VARCHAR(256)  NOT NULL DEFAULT ''  COMMENT 'SKU名称（清洗后如 Z6Pro_少年版_茶金白）',
    sku_id           VARCHAR(32)   NOT NULL DEFAULT ''  COMMENT '淘宝 SKU ID',
    sku_image_url    VARCHAR(1024) NOT NULL DEFAULT ''  COMMENT 'SKU 图片URL',
    sku_price        DECIMAL(10,2) NULL                 COMMENT '实际售价（消费者支付价）',
    original_price   DECIMAL(10,2) NULL                 COMMENT '原价（划线价）',
    activity_price   DECIMAL(10,2) NULL                 COMMENT '活动价（大促专属价）',
    crawl_time       DATETIME      NOT NULL             COMMENT '最近采集时间',
    created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    UNIQUE KEY uk_product_sku (product_id, sku_name(128)),
    INDEX idx_product_id (product_id),
    INDEX idx_sku_id (sku_id),
    INDEX idx_sku_price (sku_price)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='竞品SKU价格快照表';

-- ============================================================
-- 4. 价格历史表（price_history）
-- 每次采集追加一条，只记录实际售价，保留完整时间序列
-- 写入：sku_ingest.py — INSERT（append only）
-- 查询：alert.py — 昨日价、历史最低价
-- ============================================================
CREATE TABLE IF NOT EXISTS price_history (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY  COMMENT '自增主键',
    product_id       VARCHAR(32)   NOT NULL             COMMENT '商品ID',
    sku_name         VARCHAR(256)  NOT NULL DEFAULT ''  COMMENT 'SKU名称',
    sku_id           VARCHAR(32)   NOT NULL DEFAULT ''  COMMENT '淘宝 SKU ID',
    price            DECIMAL(10,2) NULL                 COMMENT '实际售价（NULL=无价格）',
    crawl_date       DATE          NOT NULL             COMMENT '采集日期',
    crawl_time       DATETIME      NOT NULL             COMMENT '采集时间',
    created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',

    INDEX idx_product_sku_date (product_id, sku_name, crawl_date DESC),
    INDEX idx_crawl_date (crawl_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='价格变动历史记录';

-- ============================================================
-- 5. 验证
-- ============================================================
SELECT 'V0 数据库初始化完成' AS status;
SHOW TABLES;
