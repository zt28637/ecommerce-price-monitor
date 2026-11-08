import json
import os

# 过滤规则全部来自 project-v2/config/targets.json，代码里不写死词/价格。
# 两条规则（exclude 优先）：
#   ① 标题：命中 exclude 丢弃；配了 include 且一个没命中，丢弃
#   ② 价格：取不到、低于 min_price、高于 max_price，丢弃（0 = 不限）
HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(HERE, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2",
]


def _first_dir(candidates, required="model"):
    for p in candidates:
        if not p or not os.path.isdir(p):
            continue
        if required and not os.path.exists(os.path.join(p, required)):
            continue
        return p
    return ""


PROJECT_V2 = _first_dir(_PROJECT_CANDIDATES)
CONFIG = (os.path.join(PROJECT_V2, "config", "targets.json") if PROJECT_V2 else
          os.path.normpath(os.path.join(HERE, "..", "..", "config", "targets.json")))


def load_rules(path=None):
    """取 targets.json 第一个目标；target 没写的字段用 defaults 兜底。"""
    with open(path or CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    d = cfg.get("defaults") or {}
    t = (cfg.get("targets") or [{}])[0]
    collect = dict(d.get("collect") or {})
    collect.update(t.get("collect") or {})
    return {
        "keyword": t.get("keyword") or d.get("keyword") or "",
        "include": t["include"] if "include" in t else d.get("include") or [],
        "exclude": t["exclude"] if "exclude" in t else d.get("exclude") or [],
        "min_price": t.get("min_price", d.get("min_price")) or 0,
        "max_price": t.get("max_price", d.get("max_price")) or 0,
        "collect": collect,
    }


def filter(product_list, config_path=None):
    """按配置过滤，返回通过的记录。"""
    rules = load_rules(config_path)
    passed = []
    for row in product_list or []:
        title = row.get("title") or ""
        if any(w in title for w in rules["exclude"]):
            continue
        if rules["include"] and not any(w in title for w in rules["include"]):
            continue
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            continue
        if rules["min_price"] and price < rules["min_price"]:
            continue
        if rules["max_price"] and price > rules["max_price"]:
            continue
        passed.append(row)
    return passed


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
