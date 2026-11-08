# -*- coding: utf-8 -*-
"""节点 0 · 画布契约静态检查（读转录 .md，不连影刀）。

防止重转录/手改把登录层的关键块改回旧版：
  · main：登录失败要能重建一次并终止本轮
  · login_open：调用 login_browser.ensure（DP 启动/复用）
  · login_gate：need_manual、last_login_at、Catch 写状态
  · login_qr：调用 login_entry.wait_manual、写台账、失败告警
运行：python "project-v2/model/测试/login/test_canvas_contract.py"
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # project-v2/
LOGIN = ROOT / "model" / "0.淘宝自动化登录"

CASES = [
    ("main", ROOT / "主流程_main.md", [
        ("登录门禁调用", "→login_gate", 1),
        ("重建浏览器", "→login_open", 2),
        ("浏览器故障分支", "browser_down", 1),
        ("最终终止", "退出当前流程", 2),
    ]),
    ("login_open", LOGIN / "login_open.md", [
        ("DP 启动浏览器", "login_browser", 1),
        ("调用 ensure", "ensure", 1),
        ("浏览器状态落台账", "browser_ok", 1),
    ]),
    ("login_gate", LOGIN / "login_gate.md", [
        ("人工分支", "need_manual", 1),
        ("登录时间台账", "Key=last_login_at", 1),
        ("Catch 写状态", "Key=login_state", 2),
        ("Catch 写异常", "str(exception)", 1),
        ("Catch 告警", "登录流程异常", 1),
        ("旧字段已移除", "need_qr", 0),
    ]),
    ("login_qr", LOGIN / "login_qr.md", [
        ("调用人工等待", "wait_manual", 1),
        ("成功写台账", "Key=login_state", 1),
        ("结果写台账", "Key=login_result", 1),
        ("失败告警", "方式=manual", 1),
        ("退出当前流程", "退出当前流程", 1),
    ]),
]


def main() -> int:
    failed = total = 0
    for name, path, checks in CASES:
        if not path.exists():
            print(f"FAIL {name}: 转录文件不存在 {path}")
            failed += 1
            total += 1
            continue
        text = path.read_text(encoding="utf-8")
        for desc, needle, minimum in checks:
            total += 1
            count = text.count(needle)
            ok = count >= minimum
            failed += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'} {name} · {desc}: "
                  f"期望>={minimum} 实际={count} ({needle!r})")
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
