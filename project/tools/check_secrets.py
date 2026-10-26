# -*- coding: utf-8 -*-
"""提交前敏感信息自检（2026-10-26 事故后加的闸门）

背景：曾有 database.json（MySQL 密码）与 api_config.json（JustOneAPI token）
被推上 GitHub，另有一处 token 硬编码在 api.py。删仓重建后加本脚本防复发。

用法：
    python project/tools/check_secrets.py          # 扫当前跟踪文件
    python project/tools/check_secrets.py --staged # 只扫暂存区（提交前跑）

退出码：0=干净，1=发现问题（说明里给处理建议）
"""
import re
import subprocess
import sys

# 绝不应被跟踪的文件
FORBIDDEN_FILES = {
    "project/config/database.json",
    "project/config/api_config.json",
    "project/config/collect_env.json",
    ".env",
}

# 生成的指令目录/字典：内容是参数名标签（"密码"/"令牌 Token"），不是值
SKIP_FILES = {
    "project/tools/shadowbot-canvas/sb_blocks_zh.json",
    "project/tools/shadowbot-canvas/prototype_names.json",
}

# 值形如占位符时放行
PLACEHOLDER = re.compile(r"^(<.*>|your[-_ ].*|sk-your.*|\*+|<你的.*|xxx+)$", re.I)

# (说明, 正则)
PATTERNS = [
    ("钉钉 webhook 带真实 token", re.compile(r"oapi\.dingtalk\.com/robot/send\?access_token=[A-Za-z0-9]{20,}")),
    ("钉钉加签 SEC 密钥", re.compile(r"\bSEC[0-9a-f]{40,}\b")),
    ("疑似硬编码 token/密钥变量",
     re.compile(r"^\s*(_?TOKEN|_?SECRET|_?API_KEY|_?WEBHOOK)\s*=\s*[\"'][^\"']{8,}[\"']", re.M)),
    ("配置项里出现非占位值", re.compile(r"\"(password|token|secret|api_key)\"\s*:\s*\"([^\"]+)\"")),
]


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def main() -> int:
    staged = "--staged" in sys.argv
    files = _git("diff", "--cached", "--name-only") if staged else _git("ls-files")
    files = [f.strip() for f in files.splitlines() if f.strip()]

    problems = []

    for f in files:
        if f in FORBIDDEN_FILES:
            problems.append(f"[禁止跟踪] {f} —— git rm --cached {f} 后确认 .gitignore 已覆盖")

    for f in files:
        if f in SKIP_FILES:
            continue
        if not re.search(r"\.(py|md|json|sql|txt|yaml|yml|ps1|bat)$", f, re.I):
            continue
        getter = ["show", f":{f}"] if staged else ["show", f"HEAD:{f}"]
        content = _git(*getter)
        if not content:
            continue
        for label, rx in PATTERNS:
            for m in rx.finditer(content):
                raw = m.group(0)
                # 配置项：值若是占位符则放行
                if label == "配置项里出现非占位值":
                    val = m.group(2)
                    if PLACEHOLDER.match(val.strip()) or val.strip() in ("", "null"):
                        continue
                line_no = content[:m.start()].count("\n") + 1
                problems.append(f"[{label}] {f}:{line_no}  {raw[:80]}")

    if not problems:
        print("OK：未发现敏感信息")
        return 0

    print("发现以下问题（不要提交/推送）：")
    for p in problems:
        print("  " + p)
    print("\n处理：git rm --cached <file>；代码里的真值改读环境变量/配置文件，"
          "并到对应平台重置该凭据。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
