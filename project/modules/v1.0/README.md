# v1.0 — 影刀重体系（冻结存档）

> 状态：**2026-11-02 起冻结**，只做归档与作品集展示，不再加功能。
> 对应 `VERSION.md` 的 V0.4：登录 → 采集 → SKU 深采 → 清洗 → 入库 → 日报 → 钉钉预警 → BI 看板，全链路真实跑通。

## 目录

| 环节 | 入口 | 说明 |
|------|------|------|
| ⓪ 自动化登录 | [0.淘宝自动化登录/](0.淘宝自动化登录/) | 0-0 / 0-1 / 0-2 三条画布；凭据写本地文件，不入库 |
| ① 商品数据采集 | [1.竞品商品数据采集/](1.竞品商品数据采集/) | 列表采集 + 翻页 + 通用滚动（process68） |
| ② SKU 数据采集 | [2.竞品SKU数据采集/](2.竞品SKU数据采集/) | JustOneAPI 优先 + B1/B2 网页兜底；api / api_to_datatable / sku_write |
| ③ 数据清洗 | [3.竞品数据清洗/](3.竞品数据清洗/) | `product_clean.py` → 13 列标准表 |
| ④ 数据汇总 | [4.竞品数据汇总/](4.竞品数据汇总/) | `product_ingest` / `sku_ingest` / `report` |
| ⑤ 价格告警 | [5.竞品价格告警/](5.竞品价格告警/) | `alert.py`：历史新低 / 较上次快照降价 → 钉钉 |
| ⑥ BI 看板 | [6.竞品数据看板/](6.竞品数据看板/) | Metabase 4 视图 + 12 图（纯文档） |
| 工具箱 | [工具箱/](工具箱/) | `config_loader`（词单读取）/ `random_sleep`（亚秒拟人等待） |

画布流程总表：[索引.md](索引.md)。主流程：[主流程_main.md](主流程_main.md)。

## 运行方式

1. 影刀编辑器打开旧应用「淘宝竞品价格监控自动化」。
2. 首次：跑 `0-1登录凭据设置` 写入本机凭据文件；之后 `main` 自动串登录 → 采集 → 清洗 → 日报 → 入库 → 告警。
3. Python 模块由画布「调用模块」执行，无需单独起服务；调试入口在各文件 `__main__`。

## 配置与产物

- 配置：`project/config/`（`keywords.json`、`api_config.json`、`database.json`、`collect_shadowbot.json`、`collect_env.json`）。
- 产物：`project/runtime/product_raw/`、`product_alllraw/`、`product_clean/`、`report/`、`logs/`、`profile/`。
- 数据库：MySQL `price_monitor`（3 基表 + 4 个 `v_*` 视图，DDL 见 `project/config/init_*.sql`）。

## 归档注意

- ⚠️ `1.竞品商品数据采集/product_collect_py.py`（v1 的 DrissionPage 采集器草稿）**源文件已丢失**，仓库只余 `__pycache__/product_collect_py.cpython-311.pyc`。v1 归档以影刀画布为准，该文件不再恢复；勿在文档中继续引用。
- 画布重转录：`python project/tools/shadowbot-canvas/transcribe_canvas.py <flow_id>`；v1 的 flow_id 映射已加 `v1.0/` 前缀。
- 新功能一律进 [../../../project-v2/](../../../project-v2/)，不要回改本目录。
