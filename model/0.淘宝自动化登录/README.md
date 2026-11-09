# 0. 淘宝自动化登录（v2）

> 状态：**生产级收口**。canvas 与 CodeFlow 双份，改完必须同步影刀。
> 设计源：`docs/`（本地，不入 git）。

## 一、画布拓扑

```
main (18)
 └─ login_open (4)       调 login_browser.ensure（DP 启动/复用 Edge + 固定 profile + 反自动化标识）
 └─ login_gate (16)      调 login_entry.main → 写台账 → need_manual 才进人工等待
      └─ login_qr (9)    调 login_entry.wait_manual（DP 截二维码 + 轮询离开登录域）
 └─ 登录失败：browser_down 重建一次；仍失败 → 打印日志并终止本轮
```

`login_qr` 名字沿用历史，实际是**通用人工等待**，不再只支持扫码。

## 二、CodeFlow

| 流程 | 入口 | 作用 |
|------|------|------|
| `login_browser` | `ensure() -> dict` | DP 启动/复用 Edge（固定 profile、端口、反自动化标识）；画布只读结果 |
| `login_entry` | `main(args=None) -> dict` | 判活 → 快速进入 → 人工兜底（账密默认关闭） |
| `login_entry` | `wait_manual(timeout=180) -> dict` | 人工登录等待：确保登录页 → 二维码截图 → 轮询离开登录域 |
| `login_entry` | `mark_login(method)` | 人工登录成功后写真实登录台账 |
| `login_entry` | `alert(text, title)` | 飞书优先、钉钉回退；都没配置返回 skipped |
| `classify_login` | `classify_login(page, url)` | `auto / confirm / not_login / risk / structure_error` |
| `classify_login` | `main(url)` | 画布兼容入口，返回页面状态 |

## 三、结果契约

`login_entry.main()` 固定返回：

```python
{
  "state":  "logged_in" | "cold_down",
  "method": "auto" | "quick_enter" | "password" | "manual" | "",
  "result": "ok" | "risk" | "structure_error" | "browser_down" |
            "attach_failed" | "cred_missing" | "budget_blocked" |
            "kicked_twice" | "manual_required" | "captcha" |
            "slider" | "password_failed" | "timeout",
  "need_manual": bool,   # 画布据此调 login_qr
  "stop": bool,          # 画布/main 据此终止本轮
  "login_at": str,       # 真实登录成功时间（ISO）
  "budget": {...},
  "detail": str,
}
```

`need_qr` 作为旧字段名保留，与 `need_manual` 同值。

`login_browser.ensure()` 固定返回：

```python
{
  "ok": bool,        # 浏览器可用
  "launched": bool,  # True=本次新启动；False=复用
  "detail": str,
  "port": 9223,
  "profile": str,
}
```

## 四、决策矩阵

| 页面状态 | 条件 | 动作 |
|----------|------|------|
| `auto` | 已离开登录域且认证 cookie 有效 | `logged_in / auto`，不消耗预算 |
| `confirm` | 确认面板 + 快速进入 | 点快速进入 → 等 10s → 复判；失败转人工 |
| `risk` | `sec.taobao.com` | `cold_down / risk`，告警，停跑 |
| `not_login` | 账密开关关闭（默认） | 人工等待（`need_manual`） |
| `not_login` | 账密开关打开 + 预算允许 + 有凭据 | 账密登录一次（最多 5s 复判） |
| `not_login` | 24h 内已登录 / 冷却中 | 不自动登，人工等待 + 告警 |
| `structure_error` | 页面结构不认识 | 人工等待 |

判活口径：`cookie2` 必须存在，且 `uc1 / _nk_ / unb / cookie1` 至少再命中一个；
CDP 读不到 cookie 时才退回 `tracknick`（tracknick 可能是登出后的残留值）。

## 五、登录预算与台账

| 项 | 值 |
|---|---|
| 真实登录预算 | 1 次 / 24h（快速进入、已登录不算） |
| 登录后 24h 内又失效 | 判为被踢：记冷却 24h + 告警；不自动重登，人工仍可兜底 |
| 同日连续被踢 | 2 次 → `kicked_twice`，当天停跑 |
| 自动失败重试 | 不重试 |
| 账密自动登录 | **默认关闭**（`ALLOW_PASSWORD=False`）；扫码/人工优先 |
| 人工等待 | 3 分钟（`wait_manual` 轮询 URL + 认证 cookie） |

台账（仓库外，不进 git）：

```
%USERPROFILE%\.tb_rpa\login_state.json    # last_login_at / cooldown_until / kick_count / xlly_expire
%USERPROFILE%\.tb_rpa\taobao_cred.txt     # 可选：第 1 行账号，第 2 行密码；默认不启用
runtime\run_log\login\<ts>.json # 每次登录决策的运行记录
runtime\login\qr_<ts>.png       # 人工登录时的二维码截图（gitignore）
```

`xlly_s` 到期时间只做记录/预警，**不参与判活**（到期 ≠ 会话失效）。

## 六、告警

`login_entry.alert` 先读 `model/tool/feishu_notify.py`，未配置再回退 `dingtalk_notify.py`；
两者都读 `config/alert_local.json`（gitignore），环境变量兜底。

触发点：浏览器不可用/attach 失败、风控页、24h 内重复登录、连续被踢、人工等待超时或失败、结构异常。

## 七、测试

```powershell
cd F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化
python "model\测试\login\test_login_entry.py"      # 预算/冷却/动作/人工等待 + IO 75 项
python "model\测试\login\test_classify_login.py"   # 判活真值表 14 项
python "model\测试\login\test_login_browser.py"    # DP 启动/复用 9 项
python "model\测试\login\test_canvas_contract.py"  # 画布契约静态检查 18 项
```

静态检查：影刀 `diagnostics.snapshot` 中 `main / process1 / process2 / process3 / login_entry / login_browser / classify_login` 应为 0 error。

## 八、边界

- **不绑商品、不靠 cookie 单独判活、不做静默重登、不自动取短信验证码**。
- **浏览器由 DP 启动/复用**（`login_browser.ensure`）：固定 profile + 9223 + `--disable-blink-features=AutomationControlled`；不使用无痕、不使用无头。
- 9223 没开时先由 `login_browser.ensure` 启动；启动失败才返回 `browser_down`，**不允许临时 profile**（main 负责重建一次）。
- 账密默认关闭；省登录靠 profile 常驻 + 同一浏览器复用。
- 影刀 CodeFlow 与仓库 `.py` 各一份：改仓库后必须 `codeflow.write` 同步，再跑静态检查。

## 九、待做

真机验证、配置、提交与后续节点见本地清单。
