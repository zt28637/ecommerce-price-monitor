# VERSION.md — 项目版本定义

## 当前版本：V0.3

**定义日期**：2026-09-13

### V0.3 定位

> 五层架构对齐实际文件树。商品采集 → SKU采集 → 清洗 → 汇总 → 告警，全链路可运行。

### V0.3 快照

| 维度 | 状态 |
|------|------|
| **Python 模块** | 8 个（product_clean/product_ingest/sku_ingest/report/alert + api/api_to_datatable/sku_write） |
| **影刀流程** | 6 个（商品数据采集/下一页按钮翻页/B-SKU 数据采集/B1-SKU 一维/B2-SKU 二维/子流程 C：数据清洗） |
| **数据库** | MySQL 三表（competitor_product / competitor_sku / price_history） |
| **配置** | database.json / api_config.json / init_database_v0.sql |
| **文档** | 作品规格 + 总体设计 + 反爬方案 + Agent 索引 + STAR 陈述稿 |

### V0.3 目录

```
project/
├── config/
│   ├── api_config.json
│   ├── database.json
│   ── init_database_v0.sql
├── modules/
│   ├── 1.竞品商品数据采集/
│   │   ├── 商品数据采集.flow
│   │   ├── 下一页按钮翻页.flow
│   │   └── product_collect.py
│   ├── 2.竞品 SKU 数据采集/
│   │   ├── B-SKU 数据采集.flow
│   │   ├── B1-SKU 一维数据采集.flow
│   │   ├── B2-SKU 二维数据采集.flow
│   │   ├── api.py
│   │   ├── api_to_datatable.py
│   │   └── sku_write.py
│   ├── 3.竞品信息数据清洗/
│   │   ├── 子流程 C：数据清洗.flow
│   │   └── product_clean.py
│   ├── 4.竞品数据汇总/
│   │   ├── product_ingest.py
│   │   ├── sku_ingest.py
│   │   ── report.py
│   └── 5.竞品价格告警/
│       └── alert.py
├── docs/
│   ├── agent/
│   │   ├── INDEX.md
│   │   └── 反爬增强方案.md
│   └── portfolio/
│       ├── 作品 1-淘宝竞品价格监控.md
│       ├── 作品 1-STAR.md
│       └── 项目总体设计.md
└── runtime/
    ├── logs/
    ├── product_raw/
    ├── product_cleaned/
    ├── sku_raw/
    ├── sku_cleaned/
    └── reports/
```

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| **V0** | 2026-07-21 | 三层架构基线，9 模块全链路，8 轮测试通过 |
| V0.1 | 2026-08-04 | 新增 AI 模块（ai_advisor.py）：LLM 分析 + 离线降级 |
| V0.2 | 2026-08-12 | 架构更新为 4 层（③清洗独立）；include_words 加 Z6pro/Z6Pro 型号过滤 |
| **V0.3** | **2026-09-13** | **五层架构对齐实际文件树；移除未实现的 AI 模块；文档与落地代码一致** |
