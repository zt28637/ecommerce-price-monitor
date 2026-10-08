# 淘宝竞品价格监控自动化（V0）

电商竞品价格监控系统 — 自动登录、搜索采集、SKU 深采、清洗入库、日报、钉钉预警、BI 看板。**全程无需人工改价**。

**一句话链路**：关键词搜索 → 按销量排序 → 筛出 50 个合格竞品 → 深采 SKU 价格 → 自动清洗入库 → 日报 + 降价预警 → 看板趋势分析。

## 技术栈

| 层 | 技术 |
|----|------|
| 登录 + 列表/SKU 采集 | 影刀 RPA（画布）+ Edge |
| SKU 详情数据 | JustOneAPI 优先 → 影刀网页兜底 |
| 清洗/入库/日报/告警 | Python 3（openpyxl / pymysql / requests） |
| 数据库 | MySQL 8（3 张基表 + 4 张 BI 视图） |
| 通知 | 钉钉 Webhook（降价 ≥5% / 新最低价触发） |
| 看板 | Metabase（单 jar，只读 `v_*` 视图） |

## 数据流（与影刀画布 main 一致，27 步）

```
⓪ 自动化登录        影刀画布：凭据设置 → 模拟登录
① 竞品商品数据采集   影刀画布 → 自定义数据账本导出原始 Excel
② 竞品SKU数据采集    JustOneAPI 优先 → 网页兜底（B1 一维 / B2 二维两种 SKU 结构）
③ 数据清洗          product_clean.py：价格区间过滤、掩码价丢弃 → 13 列清洗表
④ 数据汇总          product_ingest.py / sku_ingest.py 入库三表；report.py 出日报 Excel
⑤ 价格告警          alert.py → 钉钉
⑥ BI 看板           Metabase 读 v_* 视图（均价/最低价/趋势）
```

凭据与配置分三处存放：淘宝**账号/密码**（机密）由影刀弹窗写入电脑固定位置的文件（0-1 流程），不进本仓库；**搜索词单**唯一正本 [project/config/keywords.json](project/config/keywords.json)，影刀画布经 `config_loader` 模块直读（不再维护资源文件副本，蓝本见 [1-4词单config_loader改造蓝本](project/modules/1.竞品商品数据采集/1-4词单config_loader改造蓝本.md)）；**钉钉 webhook/加签**走影刀全局变量 `glv['dingtalk_webhook'] / ['dingtalk_secret']`，不在 keywords.json 里。

## 目录结构

```
project/
├── config/
│   ├── database.json · api_config.json · settings.json · promo_dates.json
│   ├── collect_shadowbot.json     # 影刀版采集调参（目标数/间隔/止损，入 git）
│   ├── init_database_v0.sql       # 三表 DDL
│   └── init_bi_views.sql          # 看板四视图 DDL（幂等，可重跑）
├── modules/
│   ├── 主流程_main.md · 索引.md    # 影刀画布逐行转录（附交叉审核疑点）
│   ├── 0.淘宝自动化登录/           # 0-0 / 0-1 / 0-2 三画布
│   ├── 1.竞品商品数据采集/         # 1-1 采集（125 步）/ 1-2 翻页
│   ├── 2.竞品SKU数据采集/          # B + B1 + B2 画布；api / api_to_datatable / sku_write
│   ├── 3.竞品数据清洗/             # product_clean.py
│   ├── 4.竞品数据汇总/             # product_ingest / sku_ingest / report
│   ├── 5.竞品价格告警/             # alert.py
│   └── 6.竞品数据看板/             # Metabase 搭建 SOP + 运维文档（无代码）
├── tools/                          # studio-mcp 画布转录脚本
└── runtime/                        # 运行时 Excel/日志（不入 git）
```

## 画布即真源

影刀流程本体在编辑器里；仓库内每个 `.md` 是由官方 studio-mcp 接口逐行转录（`python project/tools/transcribe_flows.py`），行号=画布块序号，可 diff、可 grep、密钥自动脱敏。转录覆盖与审核记录见 [project/modules/索引.md](project/modules/索引.md)。**改流程先改画布、再重新转录，不要手改 .md。**

## 快速开始

```bash
pip install -r requirements.txt

# 初始化数据库（三表）
mysql -u root -p < project/config/init_database_v0.sql

# 看板视图（用⑥才需要；CREATE OR REPLACE 幂等）
mysql -u root -p < project/config/init_bi_views.sql

# 填配置
#   project/config/database.json    MySQL 连接
#   project/config/api_config.json  JustOneAPI base_url / token

# 影刀打开应用「淘宝竞品价格监控自动化」→ 跑 0-1登录凭据设置 → 运行 main
```

看板搭建 SOP：[project/modules/6.竞品数据看板/6-0看板搭建.md](project/modules/6.竞品数据看板/6-0看板搭建.md)

## 版本

当前 **V0.3**（完整定义：[VERSION.md](VERSION.md)）。2026-09 下旬增量已落仓、未定档：⓪ 登录画布实装、⑥ Metabase 看板、影刀画布转录与交叉审核。

---

**作者**：周涛 · **用途**：RPA 开发者作品
