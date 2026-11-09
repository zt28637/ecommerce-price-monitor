# AGENTS.md — AI 协作入口

> **跨工具统一规范**。人类读者：[README.md](README.md)
> **工作区**：[../AGENTS.md](../AGENTS.md) · **系统记忆**：[../MEMORY.md](../MEMORY.md)

---

## Agent 层级（工具无关）

```text
L0 系统记忆  ../MEMORY.md              跨项目偏好 · 决策 · 踩坑
L1 全局      skills-pack/rpa/           RPA Skill + USER-CONFIG
L2 工作区    ../AGENTS.md
L3 本项目    AGENTS.md + model/
```

---

## 目录结构

```
├── AGENTS.md · CLAUDE.md · README.md    # Agent 入口 + 人类说明
├── .claude/  .cursor/  .github/  .vscode/  # 工具配置（本地，不入 git）
├── .mcp.json  .gitignore
├── model/                               # 0 登录 / 1 列表 / 2 详情 / 3 清洗 / 4 入库 / 5 告警
│   ├── 0.淘宝自动化登录/ ... 5.价格告警/
│   ├── tool/                            # feishu_notify / dingtalk_notify
│   └── 测试/                            # login / dp_list 等节点测试
├── config/                              # targets / alert / database.example（真实凭据 gitignore）
├── runtime/                             # 运行时产物 + profile（不入 git）
├── docs/                                # 设计源、测试记录、运行问题（本地，不入 git）
└── 主流程_main.md
```

> `tools/` 是本地私有工具（画布转录 MCP、密钥自检），保留在本地但**不入库**。

---

## 项目状态

> 当前仓库只维护这一条链路：登录 → 列表 → 详情 → 清洗 → 星型入库 → 告警。
> 2026-11-09 全链路实跑通过：登录 auto、列表 40、详情 40/40（704 SKU，0 失败 / 0 风控）、清洗 37 绿/3 黄、入库 40 item + 704 SKU、告警 0 条。

**策略**（以 [docs/项目优化计划-2026-10-29.md](docs/项目优化计划-2026-10-29.md) 为准）：

- 零 API、零逐个点 SKU；列表页 + 详情页 `__ICE_APP_CONTEXT__` 解析；
- **影刀负责编排与台账，DrissionPage 负责浏览器**：`login_browser.ensure` 启动/复用固定 profile + 9223 的 Edge，Python 通过 DP attach 做判活、扫码、采集、解析与落库（不另起临时 profile）；
- 登录层：DP 启动/复用 + 扫码优先 + 人工兜底；账密默认关闭；预算 1 次/24h、被踢冷却、连续 2 次停跑均在画布，见 [model/0.淘宝自动化登录/README.md](model/0.淘宝自动化登录/README.md)。

**硬性边界**：

- 不再有 v1/v2 双目录；新功能直接进 `model/`，不回改历史版本。
- 历史 v1.0 已移出仓库，归档包在 `F:\Programs\RPA自动化\_archives\淘宝竞品价格监控_v1.0_2026-11-09.zip`，只作作品集/对照引用。

---

## 硬性约束

### 凭据永不入库（硬性）

- `config/database.json` / `alert_local.json` / `login_local.json` / `collect_env.json` / `.env` **一律 gitignore**，仓库只放 `database.example.json` 占位模板
- **提交前必跑（本地工具）**：`python tools/check_secrets.py --staged`（只查暂存区），退出码非 0 不许提交；该工具本身不入库
- 2026-10-26 事故：MySQL 密码与 JustOneAPI token 曾随两个配置文件进入历史并被推送 → 已删除仓库重建、重写历史剔除、全平台轮换凭据；此后以本规则为准

### 掩码价处理

- `model/3.数据清洗` 标 `price_complete`，掩码价不进有效 SKU；保留行一律 `auto_pass`，黄标靠 `quality` / flags 留痕
- `model/4.数据入库` 只收 `auto_pass` / `approved`
- **不设人工改价步骤**；零星掩码价直接丢弃，不影响日报和预警

### 分层规则（硬性）

- **质量分级在入库前完成** —— `run_clean` 出绿/黄/红与复核状态，`run_ingest` 只入 `auto_pass` / `approved`；`pending` / `rejected` 不入
- **告警默认 dry-run** —— `run_alert` 默认 file 通道 / `--preview`；`--send` 必须人工确认后再跑
- **运行时目录**：全部在 `runtime/`（`list_html/`、`list_raw/`、`detail_html/`、`detail_json/`、`detail_raw/`、`clean/`、`alerts/`、`run_log/`、`profile/`）
- **浏览器 profile 与调试端口不进仓库**，固定 `runtime/profile` + 9223
- **元素库归影刀应用内部**，不是仓库资源

### 代码规范

- 最小改动，匹配现有文件风格
- 不主动重构
- 路径由影刀主流程传参控制；Python 模块不硬编码输出目录（本机绝对路径只作兜底）

---

## 数据库

| 模型 | 入口 |
|------|------|
| 星型模型：维度表 + 事实表 + 视图，DDL 由 `schema.py` 幂等建 | [model/4.数据入库/schema.py](model/4.数据入库/schema.py) |

- 连接配置：`config/database.json`（不入 git）
- 库：`price_monitor_v2`；测试库 `price_monitor_v2_test`

---

## 任务路由

> ⚠️ `docs/` 是**本地文档目录，不入 git**（含设计源、测试记录与运行问题）。
> GitHub 上可读的文档是：README、VERSION、AGENTS、`model/README.md`。

| 你要做… | 看这里 |
|---------|--------|
| **运行问题 / 已知隐患** | [docs/项目运行问题.md](docs/项目运行问题.md) |
| **各节点入口与命令** | [model/README.md](model/README.md) |
| **设计源 / 改架构** | `docs/`（本地，不入 git） |
| 数据库 | [model/4.数据入库/schema.py](model/4.数据入库/schema.py) |
| 配置/策略 | [config/](config/) |
| 反爬策略 | `.claude/skills/taobao-crawler.md` |
