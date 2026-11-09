"""合并：列表半边 + 详情半边 -> item（商品·天，1 行）。

合并纪律（用户 11-01 定）：
  · 只合并同粒度：item_list + item_detail -> item；**不压平 product×sku**
  · price_list / price_detail 分列，不合成一个 price
  · 详情价才是趋势价（plan §2.4c 铁律 2）；列表价只当触发器
  · 列表被过滤掉的行不进 item（在 anomalies 留过滤原因）；详情单独采到的行仍保留
"""

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)


def merge(list_items, item_details, skus):
    """返回 (items, anomalies)。

    list_items：clean_list 的通过行（passed=True）
    item_details：clean_detail 的商品级行
    skus：clean_detail 的有价 SKU 行（仅用于补 min/max 与计数校验）

    红的判定（价格非法 / 主键非法）统一交给 quality，这里只负责拼装与打信息标记。
    """
    by_pid_list = {r["product_id"]: r for r in list_items}
    by_pid_detail = {r["product_id"]: r for r in item_details}

    sku_count = {}
    sku_priced = {}
    for s in skus:
        sku_count[s["product_id"]] = sku_count.get(s["product_id"], 0) + 1
        sku_priced[s["product_id"]] = sku_priced.get(s["product_id"], 0) + 1

    keys = sorted(set(by_pid_list) | set(by_pid_detail))
    items, anomalies = [], []

    for pid in keys:
        lst = by_pid_list.get(pid)
        det = by_pid_detail.get(pid)
        day = (lst or det)["crawl_date"]

        if lst and det:
            status = "both"
        elif lst:
            status = "list_only"
        else:
            status = "detail_only"

        flags = []
        if lst:
            if lst.get("price_list_flag"):
                flags.append(lst["price_list_flag"])
        # 不在今日列表里就没有销量：detail_only 也要如实标 sales_missing
        if (lst.get("sales_flag") if lst else "sales_missing"):
            flags.append(lst["sales_flag"] if lst else "sales_missing")
        if det:
            for f in det.get("flags") or []:
                if f in ("partial_sku_price", "masked_price"):
                    flags.append("partial_sku" if f == "partial_sku_price" else f)
                elif f in ("partial_sku", "key_conflict"):
                    flags.append(f)
                elif f in ("no_sku", "sku_count_mismatch"):
                    flags.append(f)          # 信息级，由 rules 归为 info

        price_detail = det["item_price"] if det else None
        price_list = lst["price_list"] if lst else None

        if det is None:
            flags.append("detail_missing")
        elif price_detail is None and price_list is not None:
            flags.append("price_detail_missing")
        elif price_detail is None and price_list is None:
            flags.append("price_missing")

        min_sku = det["min_sku_price"] if det else None
        max_sku = det["max_sku_price"] if det else None

        item = {
            "crawl_date": day,
            "product_id": pid,
            "merge_status": status,
            "title": (det["title"] if det and det["title"] else (lst["title"] if lst else "")),
            "shop_name": (det["shop"] if det and det["shop"] else (lst["shop_name"] if lst else "")),
            "price_list": price_list,
            "price_list_raw": lst["price_list_raw"] if lst else "",
            "sales": lst["sales"] if lst else None,
            "sales_raw": lst["sales_raw"] if lst else "",
            "sales_flag": lst["sales_flag"] if lst else "sales_missing",
            "prov_city": lst["prov_city"] if lst else "",
            "main_image_url": lst["main_image_url"] if lst else "",
            "detail_url": (lst["detail_url"] if lst else (det.get("url") if det else "")),
            "platform": (lst["platform"] if lst else ""),
            "is_promoted": (lst["is_promoted"] if lst else 0),
            "passed": (lst["passed"] if lst else None),
            "filter_reason": (lst["filter_reason"] if lst else ""),
            "price_detail": price_detail,
            "price_detail_raw": det["item_price_raw"] if det else "",
            "price_desc": det["price_desc"] if det else "",
            "item_price_scope": det["item_price_scope"] if det else "",
            "hide_other_price": det["hide_other_price"] if det else None,
            "price_complete": det["price_complete"] if det else None,
            "price_coverage": det["price_coverage"] if det else "",
            # SKU 总数（含有价与无价）来自详情清洗；skus 只含有价行
            "sku_count": det["sku_count"] if det else sku_count.get(pid),
            "priced_sku_count": det["priced_sku_count"] if det else sku_priced.get(pid),
            "min_sku_price": min_sku,
            "max_sku_price": max_sku,
            "price_source": "detail" if price_detail is not None else "",
            "flags": sorted(set(flags)),
            "list_ts": lst["list_ts"] if lst else "",
            "detail_ts": det["detail_ts"] if det else "",
            "source_files": ";".join([x for x in (
                lst["source_file"] if lst else "",
                det["source_file"] if det else "") if x]),
        }
        items.append(item)
    return items, anomalies


def main(args=None):
    args = args or {}
    return merge(args.get("list_items") or [], args.get("item_details") or [],
                 args.get("skus") or [])
