# 淘宝竞品价格监控自动化

电商竞品价格监控系统 — 自动登录、关键词采集、SKU 深采、清洗入库、日报、降价预警、BI 看板。
**影刀 RPA 负责拿数据，Python 负责算数据，MySQL/Metabase 负责存与看。**

## 流程

```
登录门禁 → 列表采集(拟人滚动+翻页) → 详情采集(ICE JSON → SKU)
        → 清洗(红黄绿分级+日报) → 星型入库 → 价格告警
```

- **零 API、零逐个点 SKU**：列表页与详情页都走页面解析。
- **影刀负责编排与台账，DrissionPage 负责浏览器**：固定 profile + 9223 端口启动/复用 Edge，Python attach 同一浏览器做判活、采集、解析与落库。
- 设计源：`docs/`（本地文档，不入 git）。

## 节点与入口

| 节点 | 目录 / 入口 | 作用 |
|------|-------------|------|
| 0 登录 | [model/0.淘宝自动化登录/](model/0.淘宝自动化登录/) `login_entry.py` | 判活 → 快速进入 → 预算内账密 → 人工兜底；24h 预算 / 冷却 / 连续被踢 + 飞书告警 |
| 1 列表 | [model/1.列表页采集/](model/1.列表页采集/) `collect_list.py` | 搜索、过滤、拟人滚动、翻页、落 JSONL |
| 2 详情 | [model/2.详情页采集/](model/2.详情页采集/) `collect_detail.py` | 详情页 → ICE JSON → SKU 解析 → JSONL / HTML 留证 |
| 3 清洗 | [model/3.数据清洗/](model/3.数据清洗/) `run_clean.py` | 红黄绿分级 → Excel 报表 + JSONL |
| 4 入库 | [model/4.数据入库/](model/4.数据入库/) `run_ingest.py` | 星型模型：维度 + 事实，幂等 / 回滚 / 迟到标记 |
| 5 告警 | [model/5.价格告警/](model/5.价格告警/) `run_alert.py` | 历史新低 / 降价 / 涨幅 / 新品；文件通道优先 |
| 工具箱 | [model/tool/](model/tool/) `feishu_notify.py` | 飞书 / 钉钉通知：签名、重试、脱敏、自测 |

节点细节与命令见 [model/README.md](model/README.md)；主流程画布转录见 [主流程_main.md](主流程_main.md)。

## 目录结构

```
├── model/                 # 0 登录 / 1 列表 / 2 详情 / 3 清洗 / 4 入库 / 5 告警 + tool + 测试
├── config/                # targets / alert / database.example（真实凭据 gitignore）
├── runtime/               # 运行时产物（list_raw / detail_raw / clean / alerts / run_log / profile，不入 git）
├── docs/                  # 设计源、测试记录、运行问题（本地，不入 git）
├── 主流程_main.md
└── README.md
```

> `tools/` 是本地私有工具（画布转录 MCP、密钥自检），保留在本地但不入库。

## 快速开始

```bash
pip install -r requirements.txt

# 配置（凭据不进仓库）：
#   config/database.json、config/alert_local.json（模板见 config/database.example.json）

# 0 登录：影刀跑 login_gate / login_qr
# 1-2 采集：影刀 main 调用 collect_list / collect_detail
# 3 清洗：
python "model/3.数据清洗/run_clean.py" --date YYYY-MM-DD
# 4 入库：
python "model/4.数据入库/run_ingest.py" --date YYYY-MM-DD --init-schema
# 5 告警（默认只生成文件，不推送）：
python "model/5.价格告警/run_alert.py" --date YYYY-MM-DD --preview
```

## 工程要点

- **登录层**：DrissionPage 启动/复用固定 profile 的 Edge；判活看认证 cookie；预算 1 次/24h、被踢冷却、连续 2 次停跑；账密自动登录默认关闭，扫码/人工优先。
- **列表层**：拟人滚动 + 懒加载全覆盖；搜索页被拦（滑块/登录墙/访问频繁）返回可读 reason，不裸抛异常；翻页失败即停，避免在旧页重复采集。
- **详情层**：解析 `__ICE_APP_CONTEXT__` 拿 SKU；掩码价不计入有效 SKU；单商品异常不终结整轮。
- **清洗 / 入库**：质量分级在入库前完成，只入 `auto_pass` / `approved`；星型模型幂等、可回滚。
- **告警**：画布主流程自动推送到飞书；CLI 默认 `--preview`，补发用 `--send`；降价/涨价只在同一价格源内比较。

## 验证与边界（诚实说明）

- ✅ **全链路实跑**：登录 auto → 列表 40 条 → 详情 40/40（704 个 SKU，0 失败、0 风控命中）→ 清洗（37 绿 / 3 黄）→ 入库 40 item + 704 SKU → 告警 0 条（首日无历史）。明细见 [VERSION.md](VERSION.md)。
- ⚠️ 只针对淘宝 PC 端详情页一套 DOM；平台改版需要更新解析与元素。
- ⚠️ 采集频率未做分布式调度；长期多账号需要引入代理与队列。
- ⚠️ 画布 `main` 调详情仍为冒烟参数（`limit=3` / `interval=0`），正式跑前需改；影刀日志对 Python 模块仍偏静默，待补画布日志节点。

## 历史

v1.0（影刀重体系 V0.4）已归档，源码 / 配置 / 文档打包在仓库外：
仓库外本地归档包。版本沿革见 [VERSION.md](VERSION.md)。
