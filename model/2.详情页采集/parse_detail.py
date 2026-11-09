"""详情页解析：HTML -> __ICE_APP_CONTEXT__ -> 商品 + SKU 列表。

纯函数，不碰浏览器；影刀应用与系统 Python 都能 import。

2025 天猫模板实测（小天才电话手表详情1.html）：
  · ICE JSON 在 `var b = {...}; window.__ICE_APP_CONTEXT__=b;`
  · 商品起售价在 componentsVO.priceVO.price（priceDesc="起"）
  · skuCore.skuItem.hideOtherPrice=true 时，sku2info 只有当前 SKU 带 price，
    其他 SKU 只有 quantity / quantityText —— 解析结果标 partial_sku_price，不假装完整。
  · sku2info 的 key "0" 是汇总项，不是 SKU；不进 skus，也不当商品价。
"""

import json
import re

ICE_MARKER = "__ICE_APP_CONTEXT__"


def _extract_braced(text, start):
    """从 text[start]=='{' 起做括号配对，正确处理字符串和转义。"""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def extract_ice(html):
    """取 __ICE_APP_CONTEXT__ 的 JSON 对象。"""
    idx = html.find(ICE_MARKER)
    if idx < 0:
        raise ValueError("no __ICE_APP_CONTEXT__")

    # 2025 天猫模板：var a = window.__ICE_APP_CONTEXT__ || {}; var b = {...}; ... =b;
    j = html.find("var b = ", idx)
    if j >= 0:
        start = html.find("{", j)
        raw = _extract_braced(html, start)
        if raw:
            return json.loads(raw)

    # 旧模板：window.__ICE_APP_CONTEXT__ = {...}
    m = re.search(r"window\.__ICE_APP_CONTEXT__\s*=\s*", html[idx:])
    if m:
        start = idx + m.end()
        raw = _extract_braced(html, start)
        if raw:
            return json.loads(raw)

    # 兜底：marker 后第一个对象
    start = html.find("{", idx)
    raw = _extract_braced(html, start)
    if raw:
        return json.loads(raw)
    raise ValueError("ICE json not found")


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("￥", "").replace("¥", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _price_from_dict(p):
    """priceText 是元；priceMoney 是分。优先 priceText。"""
    if not isinstance(p, dict):
        return None
    x = _to_float(p.get("priceText"))
    if x is not None:
        return x
    m = _to_float(p.get("priceMoney"))
    if m is not None:
        return round(m / 100.0, 2)
    return None


def _prop_maps(props):
    pid_name = {}
    vid_name = {}
    for p in props or []:
        pid = str(p.get("pid"))
        pid_name[pid] = p.get("name") or ""
        for v in p.get("values") or []:
            vid_name[str(v.get("vid"))] = v.get("name") or ""
        for vid, v in (p.get("valueMap") or {}).items():
            vid_name.setdefault(str(vid), v.get("name") or "")
    return pid_name, vid_name


def _prop_names(prop_path, pid_name, vid_name):
    parts = []
    for seg in str(prop_path or "").split(";"):
        if ":" not in seg:
            continue
        pid, vid = seg.split(":", 1)
        parts.append("%s:%s" % (pid_name.get(pid, pid), vid_name.get(vid, vid)))
    return ";".join(parts)


def parse_detail(html, product_id=None):
    """HTML -> dict。失败也返回 dict（ok=False, reason=...），不抛异常。"""
    out = {"ok": False, "reason": "", "skus": [], "flags": []}
    try:
        ice = extract_ice(html)
    except Exception as e:
        out["reason"] = "ice_missing: %s" % e
        return out

    try:
        res = ice["loaderData"]["home"]["data"]["res"]
    except Exception:
        out["reason"] = "res_missing"
        return out

    item = res.get("item") or {}
    seller = res.get("seller") or {}
    sku_base = res.get("skuBase") or {}
    sku_core = res.get("skuCore") or {}
    components = res.get("componentsVO") or {}

    out["product_id"] = str(item.get("itemId") or product_id or "")
    out["title"] = item.get("title") or ""
    out["shop"] = seller.get("shopName") or ""

    sku_item = sku_core.get("skuItem") or {}
    out["hide_other_price"] = str(sku_item.get("hideOtherPrice", "")).lower() == "true"

    price_vo = (components.get("priceVO") or {}).get("price") or {}
    out["item_price"] = _price_from_dict(price_vo)
    out["item_price_raw"] = price_vo.get("priceText")
    out["price_desc"] = price_vo.get("priceDesc") or ""
    # 口径：priceDesc 含“起” = 起售价（可当最低价）；否则 hideOtherPrice 时是默认 SKU 展示价
    if "起" in out["price_desc"]:
        out["item_price_scope"] = "min"
    elif out["hide_other_price"]:
        out["item_price_scope"] = "default"
    else:
        out["item_price_scope"] = "unknown"

    pid_name, vid_name = _prop_maps(sku_base.get("props") or [])
    s2i = sku_core.get("sku2info") or {}
    skus = []
    for s in sku_base.get("skus") or []:
        sku_id = str(s.get("skuId") or "")
        info = s2i.get(sku_id) or {}
        price = _price_from_dict(info.get("price"))
        qty = info.get("quantity")
        try:
            qty = int(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        skus.append({
            "sku_id": sku_id,
            "prop_path": s.get("propPath") or "",
            "prop_names": _prop_names(s.get("propPath"), pid_name, vid_name),
            "price": price,
            "price_raw": (info.get("price") or {}).get("priceText"),
            "quantity": qty,
            "quantity_text": info.get("quantityText") or "",
            "in_stock": None if qty is None else qty > 0,
        })

    if not skus:
        # 单规格兜底：没有 skuBase.skus，用商品价造一条默认 SKU
        info0 = s2i.get("0") or {}
        qty = info0.get("quantity")
        try:
            qty = int(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        skus.append({
            "sku_id": "",
            "prop_path": "",
            "prop_names": "",
            "price": out["item_price"],
            "price_raw": out["item_price_raw"],
            "quantity": qty,
            "quantity_text": info0.get("quantityText") or "",
            "in_stock": None if qty is None else qty > 0,
        })
        out["flags"].append("no_sku")

    if s2i and len(s2i) - 1 != len(skus):
        out["flags"].append("sku_count_mismatch")

    priced = [x for x in skus if x["price"] is not None]
    out["sku_count"] = len(skus)
    out["price_coverage"] = "%d/%d" % (len(priced), len(skus))
    if out["hide_other_price"] or len(priced) < len(skus):
        out["flags"].append("partial_sku_price")
    if out["item_price"] is None and not priced:
        out["flags"].append("masked_price")
    out["price_complete"] = not any(
        f in ("partial_sku_price", "masked_price", "sku_count_mismatch")
        for f in out["flags"]
    )

    out["skus"] = skus
    out["ok"] = bool(out["product_id"] and out["title"])
    if not out["ok"]:
        out["reason"] = "item_missing"
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    path = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\runtime\samples\小天才电话手表详情1.html"
    with open(path, encoding="utf-8", errors="replace") as f:
        r = parse_detail(f.read())
    print(json.dumps({
        "ok": r["ok"],
        "product_id": r["product_id"],
        "title": r["title"][:40],
        "shop": r["shop"],
        "item_price": r["item_price"],
        "price_desc": r["price_desc"],
        "hide_other_price": r["hide_other_price"],
        "sku_count": r["sku_count"],
        "price_coverage": r["price_coverage"],
        "flags": r["flags"],
        "skus": r["skus"],
    }, ensure_ascii=False, indent=1))


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
