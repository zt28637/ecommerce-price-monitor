"""告警配置：阈值、新品规则、推送通道。

加载顺序（后者覆盖前者，深合并一层）：
  1. 本文件 DEFAULTS
  2. config/alert.json          （可入库；只放占位符，不放真实 webhook）
  3. config/alert_local.json    （不入库；放真实 webhook / secret）

webhook 支持环境变量占位：`${DINGTALK_WEBHOOK}` 或 `env:DINGTALK_WEBHOOK`。
这样仓库里永远不出现 token；换接口只改 alert_local.json 或环境变量。
"""

import json
import os
import re

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
# _MODULE_DIR 是 model/5.价格告警，退两层才到 
# 影刀把 CodeFlow 复制到 xbot_robot 下执行，相对路径会指到应用目录；
# 因此与 1.列表页采集 同款：环境变量 > 相对仓库 > 本机绝对路径。
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化",
]


def _first_project(candidates):
    for p in candidates:
        if p and os.path.isdir(os.path.join(p, "model")):
            return p
    return os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))


PROJECT_DIR = _first_project(_PROJECT_CANDIDATES)
DEFAULT_CONFIG = os.path.join(PROJECT_DIR, "config", "alert.json")
LOCAL_CONFIG = os.path.join(PROJECT_DIR, "config", "alert_local.json")
PROMO_CONFIG = os.path.join(PROJECT_DIR, "config", "promo_dates.json")

DEFAULTS = {
    "thresholds": {
        "drop_pct_daily": 5.0,      # 降价 ≥5% 进日报
        "drop_pct_instant": 10.0,   # 降价 ≥10% 即时推
        "rise_pct_daily": 5.0,
        "rise_pct_instant": 10.0,
        "new_low_instant": True,    # 创新低即使 <10% 也即时推
    },
    "new_product": {
        "enabled": True,
        "top_n": 10,                # 按销量取头部
        "days": 7,                  # 最近 N 天首次出现算新品
        "min_history_days": 3,      # 历史不足 3 天不判"进头部"（首跑全是新品）
    },
    "promo": {
        "downgrade_instant": True,  # 大促期间一律降为日报，避免狼来了
    },
    "channels": {
        "default": "file",
        "file": {"type": "file", "dir": "runtime/alerts"},
        "dingtalk": {"type": "dingtalk", "url": "${DINGTALK_WEBHOOK}",
                     "secret": "${DINGTALK_SECRET}",
                     "keyword": "${DINGTALK_KEYWORD}"},
        "feishu": {"type": "feishu", "url": "${FEISHU_WEBHOOK}"},
        "custom": {"type": "webhook", "url": ""},
    },
    "send_instant": True,           # --send 时是否发即时告警
    "send_daily": False,            # --send 时是否连日报一起发
}


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_env(value):
    """'${VAR}' / 'env:VAR' -> 环境变量值；解析不到返回空串。"""
    if not isinstance(value, str):
        return value
    s = value.strip()
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", s) or \
        re.fullmatch(r"env:([A-Za-z_][A-Za-z0-9_]*)", s)
    if m:
        return os.environ.get(m.group(1), "")
    return value


def load(path=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    for p in (path or DEFAULT_CONFIG, None if path else LOCAL_CONFIG):
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
    # 占位符解析
    for name, ch in (cfg.get("channels") or {}).items():
        if isinstance(ch, dict):
            for key in ("url", "secret", "keyword"):
                if key in ch:
                    ch[key] = resolve_env(ch[key])
    return cfg


def promo_periods(path=None):
    path = path or PROMO_CONFIG
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for _, periods in (cfg.get("promo_periods") or {}).items():
        for name, rng in (periods or {}).items():
            if rng.get("start") and rng.get("end"):
                out.append((rng["start"], rng["end"], name))
    return out


def promo_of(date, periods):
    for s, e, name in periods or []:
        if s <= date <= e:
            return name
    return None


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
