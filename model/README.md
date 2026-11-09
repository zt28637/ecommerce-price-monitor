# model/ — 节点与入口

> 状态：**开发中**（框架落地 → 登录层收口 → **全链路实跑通过**：列表 40 → 详情 40/40 · 704 SKU → 清洗 → 入库 → 告警）。
> 定版策略：零 API、零逐个点 SKU；影刀负责启动/登录浏览器，Python 通过 DrissionPage attach 复用同一浏览器做采集、解析与落库。
> 设计源：`docs/`（本地，不入 git）· 登录层细节：[0.淘宝自动化登录/README.md](0.淘宝自动化登录/README.md)

## 节点与入口

| 节点 | 目录 / 入口 | 作用 | 运行方式 |
|------|-------------|------|----------|
| 0 登录 | [0.淘宝自动化登录/](0.淘宝自动化登录/) `login_entry.py` / `classify_login.py` | 登录页判活 → 快速进入 → 预算内账密 → 人工兜底；24h 预算/冷却/连续被踢 + 飞书告警 + run_log | 影刀画布；`login_entry` / `classify_login` 可离线单测 |
| 1 列表 | [1.列表页采集/](1.列表页采集/) `collect_list.py` | 搜索、过滤、拟人滚动、翻页、落 JSONL | 影刀调用 `main(args)`；`parse_list.py` 可离线解析 HTML |
| 2 详情 | [2.详情页采集/](2.详情页采集/) `collect_detail.py` | 商品详情 → SKU 解析 → JSONL / HTML 留证 | 影刀调用；`parse_detail*.py` 可离线 |
| 3 清洗 | [3.数据清洗/](3.数据清洗/) `run_clean.py` | 列表 + 详情 → 红黄绿分级 → Excel 报表 + JSONL | `python model/3.数据清洗/run_clean.py ...` |
| 4 入库 | [4.数据入库/](4.数据入库/) `run_ingest.py` | 星型模型：维度 + 事实，幂等 / 回滚 / 迟到标记 | `python model/4.数据入库/run_ingest.py ...` |
| 5 告警 | [5.价格告警/](5.价格告警/) `run_alert.py` | 历史新低 / 降价 / 涨幅 / 新品；文件通道优先，可发送 | `python model/5.价格告警/run_alert.py --preview` |
| 工具箱 | [tool/](tool/) `feishu_notify.py` | 飞书通知：签名 / 重试 / 脱敏 / 自测；画布与 Python 共用 | `python model/tool/feishu_notify.py --test` |

主流程画布：[../主流程_main.md](../主流程_main.md)（**仓库内仍是 旧版 18 块转录，已过期**；现网 `main` 已扩到 36 块，串起 登录 → 列表 → 详情 → 清洗 → 入库 → 告警，待重新转录覆盖）。
登录层细节：[0.淘宝自动化登录/README.md](0.淘宝自动化登录/README.md)。
节点测试脚本：[测试/](测试/)。

## 常用命令

```powershell
cd F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化

# 0 登录（离线单测）
python "model\测试\login\test_login_entry.py"
python "model\测试\login\test_classify_login.py"

# 3 清洗（离线可跑）
python "model\3.数据清洗\run_clean.py" --date YYYY-MM-DD `
  --list-raw  runtime\_sample\list_raw `
  --detail-raw runtime\_sample\detail_raw

# 4 入库（先 --dry-run）
python "model\4.数据入库\run_ingest.py" --date YYYY-MM-DD --database price_monitor_v2_test --init-schema
python "model\4.数据入库\run_ingest.py" --date YYYY-MM-DD --database price_monitor_v2_test --dry-run

# 5 告警（默认 file 通道，不联网）
python "model\5.价格告警\run_alert.py" --date YYYY-MM-DD --database price_monitor_v2_test --preview
```

> `model\1.列表页采集\collect_list.py` 由影刀「调用模块」运行；直接 `python collect_list.py` 也能跑（`main(args=None)` 返回统计，见 L-01）。

## 配置（仓库根 `config/`）

| 文件 | 用途 | 状态 |
|------|------|------|
| `config/targets.json` | 采集目标（关键词、价格区间、页数、目标数） | 已入库 |
| `config/alert_local.json` | 飞书/钉钉 webhook、secret（**gitignore**） | 需按 `alert_local.example.json` 自建 |
| `config/database.json` | MySQL 连接（**gitignore**） | 需自建（模板见 `config/database.example.json`） |
| `config/keywords.json` | 旧词单（兼容读取） | 未创建，按需补 |
| `config/promo_dates.json` | 促销日期，用于告警降级 | 未创建，按需补 |
| `config/alert.json` | 告警阈值与通道（占位符可入库） | 已入库 |

## 运行时

全部落仓库根 `runtime/`：

```
list_html/ · list_raw/ · detail_html/ · detail_json/ · detail_raw/
clean/<YYYYMMDD>/ · alerts/<YYYYMMDD>/ · run_log/ · samples/ · _sample/
```

## 已知待办

- 节点 0–5 已于 全链路实跑通过（登录 auto、列表 40、详情 40/40 · 704 SKU、0 失败 / 0 风控）；
- 现网 `main` 调详情仍写死冒烟参数 `limit=3` / `interval=0`，正式跑前必须改；
- 影刀日志对 Python 模块无感（列表层只用内建 `print`，画布调用后无日志节点），静默失败难定位；
- BI 看板暂缓；
- 清洗层不再产出 `pending`：黄标保留在表里（`quality=yellow` + flags），由人看 Excel 报表核对。
