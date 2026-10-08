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
config/ · modules/{1.商品采集 2.SKU采集 3.反馈}/ · runtime/ · docs/
```

- 配置：[project/config/](project/config/)
- Python 根：[project/modules/](project/modules/)

---

## 流程速查

### 新版（独立于旧版 ABCD）

| 流程 | 内容 | 模块 |
|------|------|------|
| ① 商品数据采集 | 影刀采集 → Python 清洗 → Python 录入 MySQL | [1.竞品商品数据采集](project/modules/1.竞品商品数据采集/) |
| ② 竞品SKU数据采集 | API 采集 → 网页兜底 → SKU 清洗 → 录入 | [2.竞品SKU数据采集](project/modules/2.竞品SKU数据采集/) |
| ③ 竞品数据反馈 | 日报导出 + 钉钉价格预警 | [3.竞品数据反馈](project/modules/3.竞品数据反馈/) |

---

## 硬性约束（摘要）

- **掩码价**：`sku_ingest.py` 自动跳过，不入库
- **配置**：`project/config/`（非仓库根 `config/`）
- **Python 根**：`project/modules/`
- **完整规则**：[AGENTS.md](AGENTS.md)
