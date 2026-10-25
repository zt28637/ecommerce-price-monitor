# CLAUDE.md — Claude Code 入口（V0）

> **系统记忆**：[../MEMORY.md](../MEMORY.md) · **架构**：[AGENTS.md](AGENTS.md)

---

## 读文件顺序

1. `../MEMORY.md`
2. 本文 + `AGENTS.md`
3. [project/docs/agent/INDEX.md](project/docs/agent/INDEX.md) → 具体文件

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

## 项目主体 `project/`

```
config/ · modules/{0.登录 1.商品采集 2.SKU采集 3.清洗 4.汇总 5.告警 6.看板}/ · runtime/ · docs/
```

- 配置：[project/config/](project/config/)
- Python 根：[project/modules/](project/modules/)

---

## 流程速查

| 流程 | 内容 | 模块 |
|------|------|------|
| ⓪ 自动化登录 | 影刀画布：凭据设置 → 模拟登录 | [0.淘宝自动化登录](project/modules/0.淘宝自动化登录/) |
| ① 商品数据采集 | 影刀采集 → 自定义数据账本 | [1.竞品商品数据采集](project/modules/1.竞品商品数据采集/) |
| ② 竞品SKU数据采集 | API 优先 → 网页兜底 → 清洗 → 录入 | [2.竞品SKU数据采集](project/modules/2.竞品SKU数据采集/) |
| ③ 数据清洗 | product_clean：过滤 + 13 列标准表 | [3.竞品数据清洗](project/modules/3.竞品数据清洗/) |
| ④ 数据汇总 | 入库三表 + 日报 Excel | [4.竞品数据汇总](project/modules/4.竞品数据汇总/) |
| ⑤ 价格告警 | 历史新低 / 较上次降价 → 钉钉 | [5.竞品价格告警](project/modules/5.竞品价格告警/) |
| ⑥ BI 看板 | Metabase 4 视图 + 10 图 | [6.竞品数据看板](project/modules/6.竞品数据看板/) |

---

## 硬性约束（摘要）

- **掩码价**：`sku_ingest.py` 自动跳过，不入库
- **配置**：`project/config/`（非仓库根 `config/`）
- **Python 根**：`project/modules/`
- **完整规则**：[AGENTS.md](AGENTS.md)
