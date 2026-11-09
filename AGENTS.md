# AGENTS.md — AI 协作入口（V0）

> **跨工具统一规范**。人类读者：[README.md](README.md)
> **工作区**：[../AGENTS.md](../AGENTS.md) · **系统记忆**：[../MEMORY.md](../MEMORY.md)

---

## Agent 层级（工具无关）

```text
L0 系统记忆  ../MEMORY.md              跨项目偏好 · 决策 · 踩坑
L1 全局      skills-pack/rpa/           RPA Skill + USER-CONFIG
L2 工作区    ../AGENTS.md
L3 本项目    AGENTS.md + project/
```

---

## 目录结构

```
├── AGENTS.md · CLAUDE.md · README.md    # Agent 入口 + 人类说明
├── .claude/  .cursor/  .github/  .vscode/  # 工具配置
├── .mcp.json  .gitignore
├── project/                             # v1.0（冻结存档，计划迁出正式管理）
│   ├── config/                          # v1 独立配置（database/keywords/api_config/...）
│   ├── modules/
│   │   ├── README.md                    # v1 版本目录说明
│   │   └── v1.0/                        # 影刀重体系 V0.4 · 冻结存档
│   │       ├── 0.淘宝自动化登录/ ... 6.竞品数据看板/
│   │       ├── 工具箱/                  # config_loader / random_sleep
│   │       ├── 主流程_main.md
│   │       └── 索引.md                  # 画布 flow_id → 转录文件总表
│   ├── docs/                            # v1/shared 文档 + agent 路由（本地，不入 git）
│   ├── tools/                           # 画布转录 · 密钥自检（两版共用）
│   └── runtime/                         # v1 运行时（product_* / report / logs / profile_probe）
└── project-v2/                                # 重写版 · 当前主线（独立配置/运行时）
    ├── 0.淘宝自动化登录/ ... 5.价格告警/
    ├── 工具箱/                          # feishu_notify 等
    ├── config/                          # v2 独立配置（database/targets/alert/login）
    ├── runtime/                         # v2 运行时 + profile
    ├── docs/                            # v2 文档（本地，不入 git）
    ├── 主流程_main.md
    └── 测试/
```

---

## 版本划分（2026-11-02）

> 两版目录：[project/modules/v1.0/](project/modules/v1.0/) 与 [project-v2/](project-v2/)。
> 版本说明：[project/modules/README.md](project/modules/README.md) · [VERSION.md](VERSION.md)。

| 版本 | 状态 | 链路 | 定位 |
|------|------|------|------|
| **v1.0** | 冻结存档 · **计划迁出正式管理** | 影刀画布 + 10 个 Python 模块：登录 → 采集 → SKU 深采 → 清洗 → 入库 → 日报 → 告警 → BI | 已跑通的作品集基线（V0.4），只做只读引用 |
| **v2.0** | 当前主线（2026-11-09 全链路实跑通过） | 0 登录 → 1 列表 → 2 详情 → 3 清洗 → 4 星型入库 → 5 告警 | 2026-10-29 起重写 |

> **v1.0 迁出计划**：v1.0 将迁往独立归档仓库或本地存档，仓库正式管理范围收敛到 v2.0；迁出后 v1.0 只保留作品集/对照引用，不再接受功能修改。

**v2.0 策略**（以 [项目优化计划-2026-10-29.md](project-v2/docs/项目优化计划-2026-10-29.md) 为准）：

- 零 API、零逐个点 SKU；列表页 + 详情页 `__ICE_APP_CONTEXT__` 解析；
- **影刀负责编排与台账，DrissionPage 负责浏览器**：`login_browser.ensure` 启动/复用固定 profile + 9223 的 Edge，Python 通过 DP attach 做判活、扫码、采集、解析与落库（不另起临时 profile）；
- 登录层（2026-11-08 优化）：DP 启动/复用 + 扫码优先 + 人工兜底；账密默认关闭；预算 1 次/24h、被踢冷却、连续 2 次停跑均在画布，见 [project-v2/model/0.淘宝自动化登录/README.md](project-v2/model/0.淘宝自动化登录/README.md)。

**版本边界（硬性）**：

- v1.0 与 v2.0 **代码不互相 import**，各自带完整链路；
- **共享**：列契约、表结构；
- **配置分开**：v1 用 `project/config/`，v2 用 `project-v2/config/`，各自独立、允许各自改；
- **运行时分开**：v1 落 `project/runtime/` 根，v2 落 `project-v2/runtime/`；画布转录按 `FLOW_MAP` 的版本前缀写回；
- 新功能一律进 v2.0，不回改 v1.0。

旧的「2026-10-05 混合架构（Python 只重写 L1、L2–L5 复用）」已被 v2.0 重写取代，勿再按它实现。

---

## 硬性约束

### 凭据永不入库（硬性）

- `project/config/database.json` / `api_config.json` / `collect_env.json` / `.env` **一律 gitignore**，仓库只放 `*.example.json` 占位模板
- v2 独立配置同样不入库：`project-v2/config/database.json` / `alert_local.json` / `login_local.json` / `.env`
- **提交前必跑**：`python project/tools/check_secrets.py`（`--staged` 只查暂存区），退出码非 0 不许提交
- 2026-10-26 事故：MySQL 密码与 JustOneAPI token 曾随两个配置文件进入历史并被推送 → 已删除仓库重建、重写历史剔除、全平台轮换凭据；此后以本规则为准

### 掩码价处理

- v1.0：API（JustOneAPI）返回的价格通常是真实值；网页兜底采集到的掩码价 `?` 由 `v1.0/3.竞品数据清洗/product_clean.py` 与 `v1.0/4.竞品数据汇总/sku_ingest.py` 跳过，不入库
- v2.0：`3.数据清洗` 标 `price_complete`，掩码价不进有效 SKU；保留行一律 `auto_pass`，黄标靠 `quality` / flags 留痕；`4.数据入库` 只收 `auto_pass` / `approved`
- **不设人工改价步骤**；零星掩码价直接丢弃，不影响日报和预警

### 分层规则（硬性）

- **v1.0：清洗/校验必须在入库之前** —— `competitor_sku` 是 upsert 快照、`price_history` 是 append，脏数据落库后洗不掉
- **v1.0：告警/日报/看板三个消费者一律读 `v_*` 视图，不许裸查基表** —— `price_history` 同一 key 实测最多 32 条，裸查重复计数，会出现"日报 899 / 钉钉 909"
  - ⚠️ **现状例外（2026-10-25）**：`alert.py` 仍直查基表，但已内置与 `v_price_change` 完全相同的口径（`ROW_NUMBER` 去重 + "上一快照" + `DATE(crawl_time)=今日` 圈定），并做过逐行交叉验证
- **v1.0：报表页头摘要与 `run_stats` 必须同源** —— 两处数字不同源就是自己跟自己打架
- **v2.0：质量分级在入库前完成** —— `run_clean` 出绿/黄/红与复核状态，`run_ingest` 只入 `auto_pass` / `approved`；`pending` / `rejected` 不入
- **v2.0：告警默认 dry-run** —— `run_alert` 默认 file 通道 / `--preview`；`--send` 必须人工确认后再跑
- **⚠️ `runtime/` 目录名以实测为准**：v1 是 `product_alllraw/`（双 l，装 SKU raw）+ `product_clean/` + `report/`；v2 全部在 `runtime/v2/`
- **浏览器 profile 与调试端口两版分开**，不与影刀共用（锁冲突 + 登录态互踩）
- **元素库归各版影刀应用内部**，不是共享资源

### 代码规范

- 最小改动，匹配现有文件风格
- 不主动重构
- 路径由影刀主流程传参控制；Python 模块不硬编码输出目录

---

## 数据库

| 版本 | 模型 | 入口 |
|------|------|------|
| v1.0 | 三基表 + 4 个 `v_*` 视图：`competitor_product` / `competitor_sku`（upsert 快照）/ `price_history`（append） | [project/config/init_database_v0.sql](project/config/init_database_v0.sql) · [init_bi_views.sql](project/config/init_bi_views.sql) |
| v2.0 | 星型模型：维度表 + 事实表 + 视图，DDL 由 `schema.py` 幂等建 | [project-v2/4.数据入库/schema.py](project-v2/4.数据入库/schema.py) |

v1 用 `project/config/database.json`，v2 用 `project-v2/config/database.json`（**各自独立，均不入 git**）；v1 库 `price_monitor`，v2 库 **`price_monitor_v2`**（不共用），测试用 `price_monitor_v2_test`。

---

## 任务路由

> ⚠️ `project/docs/` 是**本地文档目录，不入 git**（含作品/面试向内容）。下表指向它的链接仅在本地有效；
> GitHub 上可读的文档是：README、VERSION、AGENTS、`project/modules/` 下的 README、画布转录与 6-x 看板教程。

| 你要做… | 看这里 |
|---------|--------|
| **v2.0 设计源 / 改架构** | **[project-v2/docs/项目优化计划-2026-10-29.md](project-v2/docs/项目优化计划-2026-10-29.md)** ← 逐节点设计、字段映射、取舍 |
| **v2.0 节点测试** | [project-v2/docs/v2-节点测试记录-2026-11-02.md](project-v2/docs/v2-节点测试记录-2026-11-02.md) |
| **文档总入口（v1/v2/shared）** | [project/docs/README.md](project/docs/README.md) |
| **v2.0 各节点入口与命令** | [project-v2/README.md](project-v2/README.md) |
| **v1.0 画布总表**（flow_id → 转录文件） | [project/modules/v1.0/索引.md](project/modules/v1.0/索引.md) |
| **v1.0 归档说明** | [project/modules/v1.0/README.md](project/modules/v1.0/README.md) |
| **版本目录与边界** | [project/modules/README.md](project/modules/README.md) |
| 详情页 SKU 解析规格（v2） | [project-v2/docs/详情页SKU解析规格-2026-11-01.md](project-v2/docs/详情页SKU解析规格-2026-11-01.md) |
| 详情页滚动施工单（v1） | [project/docs/v1.0/详情页滚动-影刀施工单v1.md](project/docs/v1.0/详情页滚动-影刀施工单v1.md) |
| 隐藏价诊断（v2） | [project-v2/docs/隐藏价诊断-hideOtherPrice-2026-11-01.md](project-v2/docs/隐藏价诊断-hideOtherPrice-2026-11-01.md) |
| 部署（v1；v2 待写） | [project/docs/v1.0/部署指南.md](project/docs/v1.0/部署指南.md) |
| 了解业务全貌 | [project/docs/shared/portfolio/作品1-淘宝竞品价格监控.md](project/docs/shared/portfolio/作品1-淘宝竞品价格监控.md) |
| 数据库 | v1 [project/config/init_database_v0.sql](project/config/init_database_v0.sql) · v2 [project-v2/4.数据入库/schema.py](project-v2/4.数据入库/schema.py) |
| 配置/策略 | v1 [project/config/](project/config/) · v2 [project-v2/config/](project-v2/config/) |
| Agent 文档索引 | [project/docs/agent/INDEX.md](project/docs/agent/INDEX.md) |
| 反爬策略 | `.claude/skills/taobao-crawler.md` |
