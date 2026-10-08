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
└── project/
    ├── config/                          # 配置（数据库/预警/策略）
    ├── modules/                         # ①商品采集 ②SKU采集 ③清洗 汇总 ⑤告警
    │   ├── 1.竞品商品数据采集/           # 影刀流程 + product_collect.py
    │   ├── 2.竞品SKU数据采集/            # B-SKU + B1 + B2 子流程 + api/api_to_datatable/sku_write
    │   ├── 3.竞品信息数据清洗/           # 子流程C + product_clean.py
    │   ├── 4.竞品数据汇总/              # product_ingest / sku_ingest / report
    │   └── 5.竞品价格告警/              # alert.py
    ├── docs/                            # 作品规格 · Agent 索引
    └── runtime/                         # 运行时数据
        ├── product_raw/                 # 商品原始 Excel（影刀采集输出）
        ├── product_cleaned/             # 商品清洗 Excel（无表头）
        ├── sku_raw/                     # SKU 原始 Excel（API + 网页兜底）
        ├── sku_cleaned/                 # SKU 清洗 Excel
        ├── reports/                     # 成品报表
        └── logs/                        # 运行日志
```

---

## 架构：五段职责（两版共同覆盖）

> **唯一真源**：[project/docs/系统架构.md](project/docs/系统架构.md) —— 双实现定位、接缝契约、L3 职责、现状差距都在那里。
> 本节只是摘要，**不要在这里展开细节**。

```text
L1 采集   影刀│DrissionPage → 接缝① raw Excel（影刀版 22 个 flow）
L2 清洗   13 列结构化      → 接缝② clean Excel
L3 校验   质量闸门         → 判定 + run_stats（必须在入库前）
L4 存储   幂等落库          → 三张基表 → 接缝③ v_* 视图
L5 输出   日报│预警│看板    → 一律读视图，并行只读
```

**一个项目、两个版本，两版都跑全流程**：

- **影刀版（用影刀 RPA）** = 重体系（分层落地、契约、闸门、留痕、配置外置）→ 米菲尔靶
- **Python 版（纯 Python + DrissionPage）** = 轻体系（脚本式、服务侧视角），**但五段一段不缺** → 革锐斯靶②/T2-6
  - **（2026-10-05 修正）混合架构**：Python 只重写 **L1 登录+采集**（DrissionPage，S2 纯网页，**不接 JustOneAPI**）；L2–L5 **直接 import 复用** `project/modules/` 现成纯 Python 模块（唯一例外 `sku_write.py` 绑 databook 退役），**同一个 `price_monitor` 库、产物落 `project/runtime/` 同一组目录**，列契约不变。代码 = **编号模块目录里的第二版文件**（如 `1.竞品商品数据采集/product_collect_py.py`，与画布转录同目录；配置复用 `collect_shadowbot.json`）；**登录验证不建**——DP profile 天然持久化登录态、首次顺手扫码即可，自动登录/失效检测=后续拓展（2026-10-05 定"先搞定项目"）；A形态(脚本驱动，默认)与 B形态(`--port` 接管带调试端口已开的页面=影刀同款形态)双支持；纯网页代价：日深采数 50→≈10。影刀采集画布退役为作品集叙事

"轻"体现在**实现**，不体现在**缺失环节**——Python 版可以没有分层目录、报表用 pandas 糊一页，但运行统计、异常过滤、清洗规则必须有（JD 的每日 SOP 不版本）。

两版考的是**两个不同能力**，不是一个能力的两种写法 → ~~不抽公共代码库、不共用一个 MySQL 库~~ **（2026-10-05 修正：落地为混合架构，L2–L5 共用既有模块与 price_monitor 库；"两个能力"的叙事由影刀画布作品集 + DrissionPage 采集器两条腿各自承担。）**

旧「数据流（5 步）」描述已废弃（把入库与报表混成一步、无校验层），细节以 `系统架构.md` 为准。

---

## 硬性约束

### 掩码价处理

- API（JustOneAPI）返回的价格通常是真实值，不经过人工
- 网页兜底采集到的掩码价 `?`：`sku_ingest.py` 自动跳过，不入库
  ⚠️ 现状如此，但**归属错了**：同一规则现在在 `product_clean.py:263,404` 和 `sku_ingest.py` 各判一次。L3 落地后只在 L3 判一次，`sku_ingest` 变纯写入。见 [系统架构.md §3](project/docs/系统架构.md)
- **不再设人工改价步骤**；零星掩码价直接丢弃，不影响日报和预警

### 分层规则（硬性）

- **L3 校验必须在 L4 入库之前** —— `competitor_sku` 是 upsert 快照、`price_history` 是 append，脏数据落库后洗不掉
- **L5 三个消费者一律读 `v_*` 视图，不许裸查基表** —— `price_history` 同一 key 实测最多 32 条，裸查重复计数，会出现"日报 899 / 钉钉 909"
- **报表页头摘要与 `run_stats` 必须同源** —— 两处数字不同源就是自己跟自己打架
- **（2026-10-05 修正，取代原"两版不共享代码、独立 schema"约束）** Python 版 = L1 采集（DrissionPage 重写）+ L2–L5 复用 `project/modules/` 既有模块，共写 `price_monitor`、共用 `project/runtime/`；**"不共享"只保留一条：浏览器 profile 与调试端口绝不与影刀共用**（锁冲突+登录态互踩）
- **⚠️ `runtime/` 目录名以实测为准，不要信文档**：实际是 `product_allraw/`（装 SKU raw）+ `product_clean/` + `report/`；文档写的 `sku_raw/` **根本不存在**
- **元素库归 L1 影刀实现内部**，不是共享资源

### 代码规范

- 最小改动，匹配现有文件风格
- 不主动重构
- 路径由影刀主流程传参控制；Python 模块不硬编码输出目录

---

## 数据库（三表）

| 表 | 用途 |
|----|------|
| `competitor_product` | 商品级 |
| `competitor_sku` | SKU 快照 upsert |
| `price_history` | 价格历史 append |

DDL：[project/config/init_database_v0.sql](project/config/init_database_v0.sql)

---

## 任务路由

| 你要做… | 看这里 |
|---------|--------|
| **改架构 / 加输出形态 / 定接缝契约** | **[project/docs/系统架构.md](project/docs/系统架构.md)** ← 架构唯一真源 |
| **影刀版采集层 · 设计**（影刀流程、参数、止损、契约） | [project/docs/采集层设计-影刀版.md](project/docs/采集层设计-影刀版.md) ← 第 1 册 |
| **影刀版采集层 · 实施与排障**（环境/失败模式/改造/验收/社区版限制） | [project/docs/采集层-影刀-实施手册.md](project/docs/采集层-影刀-实施手册.md) ← 第 2 册 |
| **影刀版采集层 · 实测证据**（真实 DOM、元素库现状、来源清单） | [project/docs/采集层-影刀-实测档案.md](project/docs/采集层-影刀-实测档案.md) ← 第 3 册 |
| **登录段画布施工**（v1 画布自闭环，不依赖 Python 模块；原《影刀画布施工单》与 `modules/采集层-影刀/` 已于 2026-09-26 有意删除、勿恢复） | [project/docs/登录段-影刀施工单v1.md](project/docs/登录段-影刀施工单v1.md) |
| ⚠️ **影刀版三册共用一套 § 编号**（不重新编号），跨册引用直接写 `§5.2` | 各册开头有分册地图列出本册 § 号 |
| **Python 版采集层（纯网页 DrissionPage）** | **[project/modules/1.竞品商品数据采集/product_collect_py.py](project/modules/1.竞品商品数据采集/product_collect_py.py)**（文件头=定位/用法/契约）+ 本文件 §架构"混合架构"条目；列契约见 §硬性约束 |
| **输出契约（列名/格式）** | 上述两份设计的 **§9**（两处一致）。⚠️ 系统架构 §2 已降级为历史存档，别照它写 |
| 了解业务全貌 | [project/docs/portfolio/作品1-淘宝竞品价格监控.md](project/docs/portfolio/作品1-淘宝竞品价格监控.md) |
| 影刀 + Python 模块 | [project/modules/](project/modules/) ①商品采集 ②SKU采集 ③清洗 汇总 ⑤告警 |
| 数据库 | [project/config/init_database_v0.sql](project/config/init_database_v0.sql) |
| 配置/策略 | [project/config/](project/config/) |
| Agent 文档索引 | [project/docs/agent/INDEX.md](project/docs/agent/INDEX.md) |
| 反爬策略 | `.claude/skills/taobao-crawler.md` |
