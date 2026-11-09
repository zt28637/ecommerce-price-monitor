# [已废弃 · 不要落画布] login_notify

2026-11-02 22:20：`login_gate` 直接 `调用模块 dingtalk_notify.main`，不再需要单独的告警视觉流程。
2026-11-08：统一走 `login_entry.alert`（飞书优先、钉钉回退），见 [README.md](README.md)。

保留此文件只作为历史记录；process5 可删除。
