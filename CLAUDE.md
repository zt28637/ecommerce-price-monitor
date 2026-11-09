# CLAUDE.md — Claude Code 入口（V0）

> **系统记忆**：[../MEMORY.md](../MEMORY.md) · **架构**：[AGENTS.md](AGENTS.md)

---

## 读文件顺序

1. `../MEMORY.md`
2. 本文 + `AGENTS.md`
3. [project-v2/README.md](project-v2/README.md) → `project-v2/docs/`（本地维护、不入 git）→ 具体文件；v1.0 文档在仓库外归档包

---

## Skills

### 自定义 Skill（本地安装）

| 触发 | 来源 | 用途 |
|------|------|------|
| **`/rpa`** | `skills-pack/rpa/` | 影刀流程规划（全局） |
| **`/frontend-design`** | `skills-pack/frontend-design/` | 前端设计 |
| **`/playwright-skill`** | `skills-pack/playwright-skill/` | 浏览器自动化 |
| 项目 `.claude/skills/generate-pluggable.md` | 项目级 | 可插拔 Python 骨架 |
| 项目 `.claude/skills/taobao-crawler.md` | 项目级 | 淘宝反爬策略 |
| **`/human-scroll`** | 项目 `.claude/skills/human-scroll/SKILL.md` | 项目级 | 随机/拟人滚动策略（懒加载全覆盖+防行为风控 · 影刀+Playwright 双实现） |
| **`/rpa-data-consistency`** | 项目 `.claude/skills/rpa-data-consistency/SKILL.md` | 项目级 | 外部快照一致性：类型守卫 / off_shelf 旁路(DLQ) / 二次确认 / 每日对账（下架·复现·新增） |

### 内置 Skill（Claude Code 自带）

`/deep-research` `/code-review` `/security-review` `/simplify` `/verify` `/run` `/init` `/review` `/loop` `/update-config` `/keybindings-help` `/claude-api` `/fewer-permission-prompts`

> 输入 `/` + Tab 查看全部。影刀规划优先 `/rpa`；方案调研用 `/deep-research`。

---

## 项目主体（v2 `project-v2/`；v1 已归档）

```
project/tools/   # 两版共用：画布转录 · 密钥自检
project-v2/      # 当前主线：model · config · runtime · docs
```

- **v1.0** = 影刀重体系（V0.4，**已归档移出仓库**，压缩包在仓库外）· **v2.0** = 重写版（当前主线）
- 配置：v2 [project-v2/config/](project-v2/config/)；v1 配置在归档包内
- Python 根：[project-v2/model/](project-v2/model/)
- v1 归档包：`F:\Programs\RPA自动化\_archives\淘宝竞品价格监控_v1.0_2026-11-09.zip`

---

## 流程速查

### v2.0（当前主线）

| 节点 | 内容 | 模块 |
|------|------|------|
| 0 登录 | 登录门禁 + 扫码/短信/密码 + 登录态台账 | [0.淘宝自动化登录](project-v2/model/0.淘宝自动化登录/) |
| 1 列表 | 搜索 → 过滤 → 拟人滚动 → 翻页 → JSONL | [1.列表页采集](project-v2/model/1.列表页采集/) |
| 2 详情 | 详情页 → ICE JSON → SKU 解析 | [2.详情页采集](project-v2/model/2.详情页采集/) |
| 3 清洗 | 质量分级 + Excel/HTML/JSONL 日报 | [3.数据清洗](project-v2/model/3.数据清洗/) |
| 4 入库 | 星型模型：幂等 / 回滚 / 迟到标记 | [4.数据入库](project-v2/model/4.数据入库/) |
| 5 告警 | 历史新低 / 降价 / 涨幅 → file / 钉钉 / 飞书 | [5.价格告警](project-v2/model/5.价格告警/) |

### v1.0（已归档移出仓库）

| 流程 | 内容 |
|------|------|
| ⓪ 自动化登录 | 影刀画布：凭据设置 → 模拟登录 |
| ① 商品数据采集 | 影刀采集 → 自定义数据账本 |
| ② 竞品SKU数据采集 | API 优先 → 网页兜底 → 清洗 → 录入 |
| ③ 数据清洗 | product_clean：过滤 + 13 列标准表 |
| ④ 数据汇总 | 入库三表 + 日报 Excel |
| ⑤ 价格告警 | 历史新低 / 较上次降价 → 钉钉 |
| ⑥ BI 看板 | Metabase 4 视图 + 12 图 |

> 源码与文档在仓库外归档包：`F:\Programs\RPA自动化\_archives\淘宝竞品价格监控_v1.0_2026-11-09.zip`

---

## 硬性约束（摘要）

- **掩码价**：v2 `3.数据清洗` 标 `price_complete`，入库只收 `auto_pass` / `approved`
- **配置**：v2 `project-v2/config/`（非仓库根 `config/`；v1 配置在归档包内）
- **Python 根**：`project-v2/model/`
- **完整规则**：[AGENTS.md](AGENTS.md)
