# CLAUDE.md — Claude Code 入口

> **系统记忆**：[../MEMORY.md](../MEMORY.md) · **架构**：[AGENTS.md](AGENTS.md)

---

## 读文件顺序

1. `../MEMORY.md`
2. 本文 + `AGENTS.md`
3. [model/README.md](model/README.md) → `docs/`（本地维护、不入 git）→ 具体文件

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

## 项目主体

```
model/       # 0 登录 / 1 列表 / 2 详情 / 3 清洗 / 4 入库 / 5 告警 + tool + 测试
config/      # targets / alert / database.example（真实凭据 gitignore）
runtime/     # 运行时产物 + profile（不入 git）
docs/        # 设计源 / 测试记录 / 运行问题（本地，不入 git）
```

> `tools/` 是本地私有工具（画布转录 MCP、密钥自检），保留在本地但不入库。

- 当前版本 **v2.0**，仓库只维护这一条链路，不再有 v1/v2 双目录。
- 配置：[config/](config/) · Python 根：[model/](model/) · 画布转录：[主流程_main.md](主流程_main.md)
- 历史 v1.0 归档包：`F:\Programs\RPA自动化\_archives\淘宝竞品价格监控_v1.0_2026-11-09.zip`

---

## 流程速查

| 节点 | 内容 | 模块 |
|------|------|------|
| 0 登录 | 登录门禁 + 扫码/短信/密码 + 登录态台账 | [model/0.淘宝自动化登录/](model/0.淘宝自动化登录/) |
| 1 列表 | 搜索 → 过滤 → 拟人滚动 → 翻页 → JSONL | [model/1.列表页采集/](model/1.列表页采集/) |
| 2 详情 | 详情页 → ICE JSON → SKU 解析 | [model/2.详情页采集/](model/2.详情页采集/) |
| 3 清洗 | 质量分级 + Excel/HTML/JSONL 日报 | [model/3.数据清洗/](model/3.数据清洗/) |
| 4 入库 | 星型模型：幂等 / 回滚 / 迟到标记 | [model/4.数据入库/](model/4.数据入库/) |
| 5 告警 | 历史新低 / 降价 / 涨幅 → file / 钉钉 / 飞书 | [model/5.价格告警/](model/5.价格告警/) |

---

## 硬性约束（摘要）

- **掩码价**：`3.数据清洗` 标 `price_complete`，入库只收 `auto_pass` / `approved`
- **配置**：`config/`（真实凭据 gitignore，模板 `database.example.json`）
- **Python 根**：`model/`
- **提交前（本地工具）**：`python tools/check_secrets.py --staged`（工具本身不入库）
- **完整规则**：[AGENTS.md](AGENTS.md)
