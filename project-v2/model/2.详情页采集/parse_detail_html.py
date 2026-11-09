"""详情页 SKU 价格解析（按《详情页SKU解析规格-2026-11-01》实现）。

契约：parse_detail_html(html) -> list[dict]，每行 6 个字段：
  sku_id / spec / price / price_fen / stock / stock_text

硬约束：
  · 只用标准库 json
  · 用字符串感知的括号配对取 JSON，不用正则截取
  · 排除 sku2info 的 key "0"（商品级起售价，不是 SKU）
  · 四条自检不过就抛 SpecCheckError，不静默通过
  · 无货 SKU 仍有价格；priceTitle 为空不影响取价

口径（必须向使用方说明）：
  priceText 是“优惠前标价”，不含促销价 / 券后价 / 到手价。
  竞品做活动降价时这个价不会变；用它算趋势得到的是“标价趋势”，不是“成交价趋势”。
"""

import json


class SpecCheckError(ValueError):
    """四条自检任一不过时抛出，report 里带逐项明细。"""

    def __init__(self, report):
        self.report = report
        super(SpecCheckError, self).__init__(
            "SKU self-check failed: " + json.dumps(report, ensure_ascii=False)
        )


def extract_json_after(html, marker):
    """从 marker 之后第一个 '{' 起，做字符串感知的括号配对，返回解析后的 dict。"""
    i = html.find(marker)
    if i < 0:
        raise ValueError("marker not found: " + marker)
    s = html.index("{", i)
    depth = 0
    in_str = False
    esc = False
    for j in range(s, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(html[s:j + 1])
    raise ValueError("unbalanced json after " + marker)


def build_spec_map(props):
    """pid -> {vid: 名称}。values 为主，valueMap 兜底。"""
    m = {}
    for p in props or []:
        pid = str(p.get("pid"))
        vals = {}
        for v in p.get("values") or []:
            vals[str(v.get("vid"))] = v.get("name") or ""
        for vid, v in (p.get("valueMap") or {}).items():
            vals.setdefault(str(vid), (v or {}).get("name") or "")
        m[pid] = vals
    return m


def spec_name(prop_path, spec_map):
    parts = []
    for seg in str(prop_path or "").split(";"):
        if ":" not in seg:
            continue
        pid, vid = seg.split(":", 1)
        parts.append(spec_map.get(pid, {}).get(vid, "%s:%s" % (pid, vid)))
    return " / ".join(parts)


def run_self_checks(skus, core, props, rows, hide_other_price=None):
    """四条自检。返回 {'ok', 'price_complete', 'coverage', 'checks', ...}。

    price_complete=False 表示“有 SKU 没价”，供下游降级；不等于结构解析失败。
    """
    keys = [k for k in core.keys() if k != "0"]

    count_ok = len(skus) == len(keys)
    missing = [str(s.get("skuId")) for s in skus if str(s.get("skuId")) not in core]
    empty_price = [r["sku_id"] for r in rows if not str(r.get("price") or "").strip()]

    expected = 1
    dims = []
    for p in props or []:
        n = len(p.get("values") or [])
        if n == 0 and p.get("valueMap"):
            n = len(p["valueMap"])
        dims.append(n)
        expected *= n
    combo_ok = expected == len(skus)

    total = len(rows)
    priced = total - len(empty_price)
    report = {
        "price_complete": len(empty_price) == 0,
        "coverage": "%d/%d" % (priced, total),
        "hide_other_price": hide_other_price,
        "checks": {
            "count": {"ok": count_ok, "skus": len(skus), "sku2info": len(keys)},
            "missing": {"ok": not missing, "missing": missing},
            "price": {"ok": not empty_price, "empty": empty_price},
            "combo": {"ok": combo_ok, "expected": expected, "actual": len(skus), "dims": dims},
        },
    }
    report["ok"] = all(v["ok"] for v in report["checks"].values())
    return report


def parse_detail_html_with_report(html, strict=True):
    """返回 (rows, report)。

    strict=True：自检不过抛 SpecCheckError（规格验收用）。
    生产建议 strict=False：读 report["price_complete"] / report["coverage"]，
    部分价不炸流程，由下游降级。
    """
    base = extract_json_after(html, '"skuBase":')
    core = extract_json_after(html, '"sku2info":')
    props = base.get("props") or []
    skus = base.get("skus") or []
    spec_map = build_spec_map(props)

    try:
        sku_core = extract_json_after(html, '"skuCore":')
        hide_other_price = str(
            (sku_core.get("skuItem") or {}).get("hideOtherPrice", "")
        ).lower() == "true"
    except Exception:
        hide_other_price = None

    rows = []
    for s in skus:
        sid = str(s.get("skuId"))
        info = core.get(sid) or {}
        price = info.get("price") or {}
        rows.append({
            "sku_id": sid,
            "spec": spec_name(s.get("propPath", ""), spec_map),
            "price": price.get("priceText"),
            "price_fen": price.get("priceMoney"),
            "stock": info.get("quantity"),
            "stock_text": info.get("quantityText"),
        })

    report = run_self_checks(skus, core, props, rows, hide_other_price=hide_other_price)
    if strict and not report["ok"]:
        raise SpecCheckError(report)
    return rows, report


def parse_detail_html(html, strict=True):
    """规格契约入口：HTML -> SKU 价格列表（每行 6 个字段）。

    strict=True 保留给规格验收；生产用 parse_detail_html_with_report(strict=False)。
    """
    rows, _ = parse_detail_html_with_report(html, strict=strict)
    return rows


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    path = sys.argv[1] if len(sys.argv) > 1 else r"d:\个人知识库\detail.html"
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    rows, report = parse_detail_html_with_report(html, strict=False)
    print("rows:", len(rows))
    print("self-check:", json.dumps(report, ensure_ascii=False, indent=1))
    print("--- first 5 ---")
    for r in rows[:5]:
        print(json.dumps(r, ensure_ascii=False))

    expected = {
        "5949255181297": ("63.06", 200),
        "5949255181294": ("68.94", 200),
        "5949255181295": ("73.65", 200),
        "5949255181296": ("80.71", 200),
        "5643240233629": ("86.59", 0),
    }
    got = {r["sku_id"]: (r["price"], r["stock"]) for r in rows}
    bad = {k: {"expected": v, "got": got.get(k)} for k, v in expected.items() if got.get(k) != v}
    print("acceptance:", "PASS" if not bad and report["ok"] and len(rows) == 21 else "FAIL")
    if bad:
        print("mismatch:", json.dumps(bad, ensure_ascii=False, indent=1))
    sys.exit(0 if not bad and report["ok"] and len(rows) == 21 else 1)


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
