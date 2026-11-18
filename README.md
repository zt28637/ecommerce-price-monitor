# 竞品价格监控自动化 · 方案与下游实现展示

> 运营在 Excel 里改关键词和价格区间，一条命令跑完采集、清洗、入库、告警，产出一份业务能直接看的 Excel 日报和 Markdown 告警日报。

**说明**：本仓库是**方案与下游工程实现**的展示，不是完整可运行版本。采集层（登录、找卡、滚动、风控、mtop、节奏）属于核心实现，**不公开**；本仓库通过架构与契约文档说明其行为。完整代码可在面试时现场走读。

---

## 1. 公开范围

| 已包含 | 不包含（私有） |
|---|---|
| 架构总览、节点地图、节点契约、影刀壳 | 登录层实现（N0） |
| 清洗层代码（N3） | 列表采集实现（N1）：搜索、滚动、解析、翻页、风控识别 |
| 入库层代码（N4）：schema、维度/事实、幂等 | 详情采集实现（N2）：找卡点击、ICE/mtop 解析、节奏、风控状态机 |
| 告警层代码（N5）：规则、去重、渲染、通知 | 内部测试记录、实测数据、真实商品样本 |
| 业务配置校验（Excel → targets.json） | 影刀画布工程文件 |
| 飞书通知工具 | 真实凭据与运行产物 |

> 采集层对外只暴露**输入 / 输出 / 失败分类**（见 [docs/节点契约.md](docs/节点契约.md)），实现细节不随仓库分发。

---

## 2. 业务问题

电商运营每天要手动搜关键词、翻页、进详情、抄竞品价格，再整理成表。重复、耗时、容易漏。

这个项目把这条链路自动化：

- 运营只碰一张 `监控关键词.xlsx`；
- 维护人员一条命令跑批；
- 业务直接看 `日报_<日期>.xlsx` 和 `告警_<日期>.md`。

---

## 3. 方案

```text
监控关键词.xlsx（运营改）
      │ config_excel.py 校验
      ▼
config/targets.json
      │ run_batch（私有编排）
      ▼
┌──────────── 采集层（私有实现） ────────────┐
│ N0 登录 → N1 列表 → N2 详情                 │
│ 只通过契约输出：list_raw / detail_raw JSONL │
└────────────────────┬───────────────────────┘
                     ▼
N3 清洗 → N4 入库 → N5 告警
      │
      ├─ runtime/clean/<日期>/日报_<日期>.xlsx    ← 业务看
      └─ runtime/alerts/<日期>/告警_<日期>.md     ← 业务看
```

采集层与下游之间是文件契约：N2 产出冻结字段的 JSONL，N3 起的代码在本仓库完整可见。

---

## 4. 建议阅读顺序

1. [docs/架构总览.md](docs/架构总览.md) — 系统边界、进程模型、节点总表、数据契约
2. [docs/节点契约.md](docs/节点契约.md) — 每个节点的输入、输出、失败分类
3. [docs/节点地图.md](docs/节点地图.md) — 子节点拆分与施工粒度
4. [docs/影刀壳.md](docs/影刀壳.md) — 影刀业务编排（触发 / 状态判断 / 通知）
5. 代码：`model/3.数据清洗/` → `model/4.数据入库/` → `model/5.价格告警/`

---

## 5. 下游代码说明

### N3 清洗（`model/3.数据清洗/`）

- `input_clean.py`：读 list/detail 原始 JSONL
- `clean_list.py` / `clean_detail.py`：字段标准化、去重、价格完整性判断
- `clean_merge.py`：列表与详情合并成商品行
- `rules.py`：红黄绿分级规则
- `export.py`：Excel 日报（openpyxl）
- `verify_clean.py`：产物校验
- `run_clean.py`：入口编排

### N4 入库（`model/4.数据入库/`）

- `schema.py`：5 表 + 4 视图
- `ingest_dim.py`：维度 SCD2
- `ingest_fact.py`：事实 upsert
- `db.py`：连接与配置
- `run_ingest.py`：批次事务 / dry-run / 回滚

### N5 告警（`model/5.价格告警/`）

- `alert_build.py`：阈值、稳定 `alert_id`、24h 冷却
- `notify.py`：file / 飞书通道
- `run_alert.py`：入口编排

### 业务配置（`model/7.业务侧/`）

- `config_excel.py`：`监控关键词.xlsx` → 校验 → `targets.json`
- `notify_cli.py`：影刀失败/部分完成通知入口

### 工具（`model/tool/`）

- `paths.py`：项目路径 SSOT
- `feishu_notify.py`：飞书签名、重试、脱敏

---

## 6. 技术栈

- Python 3.11
- MySQL（事实表/维度表）
- openpyxl（Excel 配置与日报）
- pytest（离线回归）
- 影刀（业务入口：触发 + 状态判断 + 失败通知）

采集层使用 Playwright 通过 CDP 接管固定 Edge 登录态；该部分实现不在此仓库。

---

## 7. 边界（主动说）

- 单账号、低频、顺序跑；不做代理池、多账号、并发采集；
- 不做角色权限、审批流、仪表盘、告警处理流；
- 不做自动调价；
- 完整编排层已归档，只保留业务侧薄跑批。

---

## 8. 运行说明

本仓库**不包含采集层**，因此无法端到端跑批。可独立运行的部分：

```bash
pip install -r requirements.txt

# 校验 Excel 配置（不写 targets.json）
python model/7.业务侧/config_excel.py --check

# 用已有 list_raw/detail_raw 跑清洗
python model/3.数据清洗/run_clean.py --date YYYY-MM-DD \
  --list-raw runtime/list_raw --detail-raw runtime/detail_raw
```

N4/N5 需要 MySQL 与采集产物；没有采集层时只作为实现参考。

---

## 9. 目录

```text
├── README.md
├── requirements.txt
├── config/                 # targets / alert + 示例（真实凭据不入库）
├── docs/                   # 架构 / 节点地图 / 节点契约 / 影刀壳
└── model/
    ├── 3.数据清洗/
    ├── 4.数据入库/
    ├── 5.价格告警/
    ├── 7.业务侧/           # Excel 配置校验 + 通知入口
    └── tool/               # 路径 SSOT + 飞书通知
```
