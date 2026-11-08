# v2.0 — 重写版（当前主线）

> 状态：**开发中**（2026-11-01 框架落地；2026-11-08 登录层收口，待真机验证）。
> 定版策略：零 API、零逐个点 SKU；影刀负责启动/登录浏览器，Python 通过 DrissionPage attach 复用同一浏览器做采集、解析与落库。
> 设计源：[项目优化计划-2026-10-29.md](docs/项目优化计划-2026-10-29.md) · 登录层细节：[model/0.淘宝自动化登录/README.md](model/0.淘宝自动化登录/README.md)

## 节点与入口

| 节点 | 目录 / 入口 | 作用 | 运行方式 |
|------|-------------|------|----------|
| 0 登录 | [model/0.淘宝自动化登录/](model/0.淘宝自动化登录/) `login_entry.py` / `classify_login.py` | 登录页判活 → 快速进入 → 预算内账密 → 人工兜底；24h 预算/冷却/连续被踢 + 飞书告警 + run_log | 影刀画布；`login_entry` / `classify_login` 可离线单测 |
| 1 列表 | [model/1.列表页采集/](model/1.列表页采集/) `collect_list.py` | 搜索、过滤、拟人滚动、翻页、落 JSONL | 影刀调用 `main(args)`；`parse_list.py` 可离线解析 HTML |
| 2 详情 | [model/2.详情页采集/](model/2.详情页采集/) `collect_detail.py` | 商品详情 → SKU 解析 → JSONL / HTML 留证 | 影刀调用；`parse_detail*.py` 可离线 |
| 3 清洗 | [model/3.数据清洗/](model/3.数据清洗/) `run_clean.py` | 列表 + 详情 → 红黄绿分级 → Excel 报表 + JSONL | `python run_clean.py ...` |
| 4 入库 | [model/4.数据入库/](model/4.数据入库/) `run_ingest.py` | 星型模型：维度 + 事实，幂等 / 回滚 / 迟到标记 | `python run_ingest.py ...` |
| 5 告警 | [model/5.价格告警/](model/5.价格告警/) `run_alert.py` | 历史新低 / 降价 / 涨幅 / 新品；文件通道优先，可发送 | `python run_alert.py --preview` |
| 工具箱 | [model/tool/](model/tool/) `feishu_notify.py` | 飞书通知：签名 / 重试 / 脱敏 / 自测；画布与 Python 共用 | `python model/tool/feishu_notify.py --test` |

主流程画布：[主流程_main.md](主流程_main.md)（18 块：启动 Edge → 登录门禁 → browser_down 重建一次 → 仍失败则终止本轮；列表之后未接）。
登录层细节：[model/0.淘宝自动化登录/README.md](model/0.淘宝自动化登录/README.md)。
节点测试脚本：[测试/](测试/)。

## 常用命令

```powershell
cd F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2

# 0 登录（离线单测）
python "model\测试\login\test_login_entry.py"
python "model\测试\login\test_classify_login.py"

# 3 清洗（离线可跑）
python "model\3.数据清洗\run_clean.py" --date 2026-11-01 `
  --list-raw  runtime\_sample\list_raw `
  --detail-raw runtime\_sample\detail_raw

# 4 入库（先 --dry-run）
python "model\4.数据入库\run_ingest.py" --date 2026-11-01 --database price_monitor_v2_test --init-schema
python "model\4.数据入库\run_ingest.py" --date 2026-11-01 --database price_monitor_v2_test --dry-run

# 5 告警（默认 file 通道，不联网）
python "model\5.价格告警\run_alert.py" --date 2026-11-01 --database price_monitor_v2_test --preview
```

> `model\1.列表页采集\collect_list.py` 由影刀「调用模块」运行；直接 `python collect_list.py` 也能跑（`main(args=None)` 返回统计，见 L-01）。

## 配置

| 文件 | 用途 | 状态 |
|------|------|------|
| `config/targets.json` | 采集目标（关键词、价格区间、页数、目标数） | 已入库 |
| `config/alert_local.json` | 飞书/钉钉 webhook、secret（**gitignore**） | 需按 `alert_local.example.json` 自建 |
| `config/database.json` | MySQL 连接（**gitignore**） | 需自建（可参考 `project/config/database.json`） |
| `config/keywords.json` | 旧词单（兼容读取） | 未创建，按需补 |
| `config/promo_dates.json` | 促销日期，用于告警降级 | 未创建，按需补 |
| `config/alert.json` | 告警阈值与通道（占位符可入库） | 未创建，代码有内置默认 |

## 运行时

全部落 `project-v2/runtime/`：

```
list_html/ · list_raw/ · detail_html/ · detail_json/ · detail_raw/
clean/<YYYYMMDD>/ · alerts/<YYYYMMDD>/ · run_log/ · samples/ · _sample/
```

## 已知待办

- **待做清单：[docs/登录层-验证与后续清单-2026-11-08.md](docs/登录层-验证与后续清单-2026-11-08.md)**（P0 真机验证 → P1 配置 → P2 提交 → P3 列表采集）；
- 节点 0 已收口（2026-11-08），待真机跑一轮验证快速进入/人工等待/预算拦截；
- 主流程只串到登录层，列表 → 详情 → 清洗 → 入库 → 告警未接；
- BI 看板暂缓；
- 清洗层不再产出 `pending`：黄标保留在表里（`quality=yellow` + flags），由人看 Excel 报表核对。
