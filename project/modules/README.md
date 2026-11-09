# modules — v1.0 目录（v2 已抽到同级 `../../project-v2/`）

本目录只放 **v1.0 冻结代码**；v2.0 已独立到仓库根的同级目录 `project-v2/`。
两版**不互相 import、不共用 Python 包、不共用配置**；只共享列契约与表结构。

> **v1.0 去向**：已冻结，**计划迁出正式管理**（独立归档仓库或本地存档）；本仓库后续只维护 v2.0，v1.0 不再接受功能修改。

| 目录 | 对应版本 | 状态 | 定位 |
|------|----------|------|------|
| [v1.0/](v1.0/) | V0.4 | **冻结存档 · 计划迁出正式管理**（2026-11-02 起冻结） | 影刀重体系：画布为主 + 10 个 Python 模块，只保留作品集与对照引用 |
| [../../project-v2/](../../project-v2/) | 2.0 | **当前主线**（开发中） | 重写版：登录门禁 → 列表 → 详情 → 清洗 → 星型入库 → 告警 |

## 边界

- **代码**：v1.0 与 v2.0 各自独立，禁止跨版本 `import`。
- **配置**：**不共用**。v1 用 `project/config/`；v2 用 `project-v2/config/`；`database` / `keywords` / `promo_dates` 各有一份。
- **运行时**：v1.0 落 `project/runtime/` 根目录（`product_raw/`、`product_alllraw/`、`product_clean/`、`report/`、`logs/`、`profile_probe/`）；v2.0 落 `project-v2/runtime/`（含 `profile/`）。
- **画布转录**：`project/tools/shadowbot-canvas/transcribe_canvas.py` 的 `FLOW_MAP` 已按版本分路径；切应用后按 flow_id 重转，勿混写。

## 读哪个

- **跑当前采集/入库/告警** → [../../project-v2/README.md](../../project-v2/README.md)
- **看已完成的作品集链路（影刀 + 全 Python 模块）** → [v1.0/README.md](v1.0/README.md)
- **架构与版本取舍** → [../../AGENTS.md](../../AGENTS.md) · [../../VERSION.md](../../VERSION.md)
