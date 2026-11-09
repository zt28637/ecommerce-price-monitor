"""
============================================================
② SKU 数据采集 — API 响应解析模块
============================================================
作用：把 api.py 返回的原始 JSON → 解析成 13 列标准行，供影刀写入数据表格

核心任务：
  1. 解析 propPath + sku_props → 人类可读的 SKU 名称（如 "茶金白;少年版"）
  2. 匹配 sku_images → SKU 属性图片 URL
  3. 提取三档价格：实际售价 / 原价 / 活动价
  4. 与商品级数据合并，输出 13 列标准格式

输出 13 列顺序（与 sku_clean.py / SKU原始数据表格结构.md 严格一致）：
  商品ID → 商品名称 → 店铺名称 → 商品主图链接 →
  SKUID → SKU名称 → SKU图片链接 →
  实际售价 → 原价 → 活动价 →
  销量 → 采集时间 → 数据来源

调用方式（影刀）：
  模块：api_to_datatable
  方法：main
  参数：product_id, product_name, shop_name, main_image_url,
        sales, crawl_time, api_result
  结果保存到：sku_rows_json（JSON 数组）
============================================================
"""

import json

try:
    from xbot import print as _xbot_log   # 影刀内运行 → 写流程日志
except ImportError:                        # 离线单测无 xbot → 静默
    def _xbot_log(*args, **kwargs):
        pass


def _safe_str(value) -> str:
    """安全转字符串：None → "" """
    return "" if value is None else str(value)


def _fix_url(url: str) -> str:
    """补全图片链接协议头：//img.alicdn.com/... → https://img.alicdn.com/..."""
    url = _safe_str(url)
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return url


def _api_data(api_result) -> dict:
    """安全取 api_result["data"]：商品下架等异常时 data 是字符串提示语（如"商品已经下架"）而非 dict"""
    d = api_result.get("data", {}) if isinstance(api_result, dict) else {}
    return d if isinstance(d, dict) else {}


# ============================================================
# 价格提取
# ============================================================

def _pick_prices(sku: dict) -> tuple:
    """
    从单个 SKU 的 JSON 对象中提取三档价格

    JustOneAPI 每个 SKU 有三个价格字段：
      price           — 原价（划线价）
      promotion_price — 促销价
      activity_price  — 活动价（大促如 618/双11 专属价）

    规则：
      实际售价 = activity_price ?? promotion_price ?? price
      原价     = price
      活动价   = activity_price（没有就留空）

    返回：(实际售价, 原价, 活动价) — 均为字符串
    """
    # 提取原始值
    price = _safe_str(sku.get("price")).strip()
    promotion = _safe_str(sku.get("promotion_price")).strip()
    activity = _safe_str(sku.get("activity_price")).strip()

    # 清洗 "null" 字符串 → ""
    if price.lower() == "null":
        price = ""
    if promotion.lower() == "null":
        promotion = ""
    if activity.lower() == "null":
        activity = ""

    original_price = price
    activity_price = activity

    # 实际售价：活动价 > 促销价 > 原价
    real_price = activity_price or promotion or original_price

    return real_price, original_price, activity_price


# ============================================================
# SKU 名称解析
# ============================================================

def _parse_prop_path(prop_path: str, sku_props: list) -> str:
    """
    把淘宝的 SKU 属性编码 → 人类可读的名称

    淘宝用数字 ID 表示属性：
      propPath   = "21433:21373;1627207:23023534496"
      sku_props  = [{pid:"21433", values:[{vid:"21373", name:"14寸"}]}, ...]
      ↓ 解析后
      "14寸;【各版本区别说明】"

    参数:
        prop_path : 属性路径字符串，格式 "pid:vid;pid:vid"
        sku_props : 属性定义列表（来自 API 的 data.item.sku_props）

    返回:
        人类可读的 SKU 名称，如 "茶金白;少年版"
    """
    if not prop_path or not sku_props:
        return ""

    # 第一步：建立 (pid, vid) → name 的查找表
    prop_map = {}  # {pid: {vid: name}}
    for prop in sku_props:
        pid = _safe_str(prop.get("pid"))
        if not pid:
            continue
        values = {}
        for v in prop.get("values", []):
            vid = _safe_str(v.get("vid"))
            if vid:
                values[vid] = _safe_str(v.get("name"))
        prop_map[pid] = values

    # 第二步：遍历 propPath 中的每一段 pid:vid，查出对应的 name
    parts = []
    for segment in _safe_str(prop_path).split(";"):
        segment = segment.strip()
        if ":" not in segment:
            continue
        pid, vid = segment.split(":", 1)
        name = prop_map.get(pid.strip(), {}).get(vid.strip(), "")
        if name:
            parts.append(name)

    return ";".join(parts)


# ============================================================
# SKU 图片匹配
# ============================================================

def _sku_image_url(prop_path: str, sku_images: dict) -> str:
    """
    从 sku_images 中找到当前 SKU 对应的属性图片

    sku_images 的 key 格式是 "pid:vid"，如 "1627207:23023534496"
    找第一个匹配的属性图片链接

    返回: 补全协议头的图片 URL，没有则返回 ""
    """
    if not prop_path or not sku_images:
        return ""

    for segment in _safe_str(prop_path).split(";"):
        segment = segment.strip()
        if segment in sku_images:
            return _fix_url(sku_images[segment])

    return ""


# ============================================================
# SKU 关键词过滤
# ============================================================

def _filter_by_keywords(skus: list, keywords) -> list:
    """
    按 SKU 名称过滤：仅保留名称中包含任意关键词的 SKU

    参数:
        skus     : parse_api_skus 返回的 SKU 字典列表
        keywords : 关键词列表，如 ["少年版", "标准版", "pro"]
                   空列表/None → 不过滤，全量保留

    返回:
        过滤后的 SKU 列表（顺序不变）
    """
    if not keywords:
        return skus

    # 兼容 JSON 字符串：影刀可能传入 '["少年版","标准版"]'
    if isinstance(keywords, str):
        keywords = json.loads(keywords)
    if not isinstance(keywords, list):
        return skus

    # 清洗：去空白、忽略大小写比较
    cleaned = [str(k).strip().lower() for k in keywords if str(k).strip()]
    if not cleaned:
        return skus

    filtered = []
    for sku in skus:
        name = _safe_str(sku.get("sku_name")).lower()
        if any(kw in name for kw in cleaned):
            filtered.append(sku)

    return filtered


# ============================================================
# 主解析函数
# ============================================================

def parse_api_skus(api_result) -> list:
    """
    解析 JustOneAPI 原始响应 → 标准 SKU 字典列表

    参数:
        api_result : api.py 返回的原始 JSON（dict 或 JSON 字符串）

    返回:
        [
          {
            "sku_id": "5095300330629",
            "sku_name": "14寸;深空灰",
            "sku_image_url": "https://img.alicdn.com/...",
            "real_price": "79.9",
            "original_price": "199",
            "activity_price": ""
          },
          ...
        ]
    """
    # 参数校验
    if not api_result:
        return []

    # 兼容 JSON 字符串
    if isinstance(api_result, str):
        api_result = json.loads(api_result)

    # 校验 API 返回码
    if not isinstance(api_result, dict):
        return []
    if api_result.get("code") != 0:
        return []

    data = _api_data(api_result)

    # ── 格式 1：data.skus（新版本，价格是分）──
    skus_raw = data.get("skus")
    if skus_raw and isinstance(skus_raw, list):
        props = data.get("props", []) or []
        name_map, img_map = {}, {}
        for p in props:
            for v in p.get("values", []):
                vid = _safe_str(v.get("vid"))
                if vid:
                    name_map[vid] = _safe_str(v.get("vname"))
                    img_map[vid] = _fix_url(_safe_str(v.get("sku_url")))
        skus = []
        for sku in skus_raw:
            sid = _safe_str(sku.get("skuId"))
            raw_id = _safe_str(sku.get("id"))
            vid = raw_id.split(":")[-1] if ":" in raw_id else ""
            try:
                rp = str(float(_safe_str(sku.get("price"))) / 100)
            except Exception:
                rp = _safe_str(sku.get("price"))
            try:
                op = str(float(_safe_str(sku.get("orign_price"))) / 100)
            except Exception:
                op = _safe_str(sku.get("orign_price"))
            skus.append({"sku_id": sid, "sku_name": name_map.get(vid, ""),
                          "sku_image_url": img_map.get(vid, ""),
                          "real_price": rp, "original_price": op, "activity_price": ""})
        return skus

    # ── 格式 4：data.sku2info（SKU名可直接读，价格是分）──
    sku2info = data.get("sku2info")
    if sku2info and isinstance(sku2info, list):
        skus = []
        for sku in sku2info:
            sid = _safe_str(sku.get("skuId"))
            sname = _safe_str(sku.get("skuName"))
            simg = _fix_url(_safe_str(sku.get("skuPicUrl")))

            # 价格是分 → 元
            fs = _safe_str(sku.get("finalSkuPrice"))
            try:
                rp = str(float(fs) / 100) if fs else ""
            except Exception:
                rp = fs

            to = _safe_str(sku.get("thirdOriginalDiscountPrice") or sku.get("itemPrice"))
            try:
                op = str(float(to) / 100) if to else ""
            except Exception:
                op = to

            if not sid and not sname:
                continue
            skus.append({"sku_id": sid, "sku_name": sname,
                         "sku_image_url": simg,
                         "real_price": rp, "original_price": op,
                         "activity_price": ""})
        return skus

    # ── 格式 3：data.itemSkuDO（skuList 为 dict，无SKU级价格）──
    # itemSkuDO 可能在 data 层级，也可能在 data.item 内（API版本差异）
    item = data.get("item", {})
    item_sku_do = data.get("itemSkuDO") or item.get("itemSkuDO")
    if item_sku_do and isinstance(item_sku_do, dict):
        sku_list = item_sku_do.get("skuList", {}) or {}
        sku_property_list = item_sku_do.get("skuPropertyList", []) or []

        if sku_list and sku_property_list:
            # 建立 vid → name / image 查找表
            vid_name_map = {}
            vid_image_map = {}
            for prop in sku_property_list:
                for pv in prop.get("propertyValues", []):
                    vid = _safe_str(pv.get("vid"))
                    if vid:
                        vid_name_map[vid] = _safe_str(pv.get("name"))
                        vid_image_map[vid] = _fix_url(_safe_str(pv.get("image")))

            # 价格从商品级取（此格式 SKU 无独立价格）
            # itemPrice 同样可能在 data 层级或 data.item 内
            item_price = data.get("itemPrice") or item.get("itemPrice") or {}
            op = _safe_str(item_price.get("originalPrice"))
            pp = _safe_str(item_price.get("promotionPrice"))
            rp = pp or op  # 实际售价 = 促销价 ?? 原价

            skus = []
            for sku_id_str, sku_data in sku_list.items():
                prop_path = sku_data.get("propPath", "")
                vid = prop_path.split(":")[-1] if ":" in prop_path else ""

                skus.append({
                    "sku_id": _safe_str(sku_data.get("skuId", sku_id_str)),
                    "sku_name": vid_name_map.get(vid, ""),
                    "sku_image_url": vid_image_map.get(vid, ""),
                    "real_price": rp,
                    "original_price": op,
                    "activity_price": "",
                })
            return skus

    # ── 格式 2：data.item.sku_base（旧版本）──
    sku_base = item.get("sku_base", []) or []
    sku_props = item.get("sku_props", []) or []
    sku_images = item.get("sku_images", {}) or {}

    # 逐条解析
    skus = []
    for sku in sku_base:
        prop_path = sku.get("propPath")

        sku_id = _safe_str(sku.get("skuId"))

        # SKU名称：优先取 API 直接返回的字段，没有才从 propPath 解析
        sku_name = _safe_str(sku.get("properties_name"))
        if not sku_name:
            sku_name = _parse_prop_path(prop_path, sku_props)
        if not sku_name:
            sku_name = _safe_str(sku.get("sku_name"))
        sku_image = _sku_image_url(prop_path, sku_images)
        real_price, original_price, activity_price = _pick_prices(sku)

        # 跳过既无 ID 也无名称的无效 SKU
        if not sku_id and not sku_name:
            continue

        skus.append({
            "sku_id": sku_id,
            "sku_name": sku_name,
            "sku_image_url": sku_image,
            "real_price": real_price,
            "original_price": original_price,
            "activity_price": activity_price,
        })

    return skus


# ============================================================
# 组装 13 列标准行
# ============================================================

def format_rows(product_info: dict, api_result, include_keywords=None) -> str:
    """
    将商品级数据 + API 响应 → 组装成 13 列行的 JSON 字符串

    参数:
        product_info      : {"product_id": "..", "product_name": "..",
                             "shop_name": "..", "main_image_url": "..",
                             "sales": "..", "crawl_time": ".."}
        api_result        : api.py 返回的原始 JSON
        include_keywords  : SKU 名称过滤关键词列表，如 ["少年版","标准版"]
                            空/None → 不过滤；传入后仅保留含关键词的 SKU

    返回:
        JSON 数组字符串，每个元素是 13 个字段的字典
    """
    product_info = product_info or {}

    # 商品级数据（所有 SKU 共享）
    base = {
        "商品ID":   _safe_str(product_info.get("product_id")),
        "商品名称":  _safe_str(product_info.get("product_name")),
        "店铺名称":  _safe_str(product_info.get("shop_name")),
        "商品主图链接": _safe_str(product_info.get("main_image_url")),
        "销量":     _safe_str(product_info.get("sales")),
        "采集时间":  _safe_str(product_info.get("crawl_time")),
    }

    # ── 解析 SKU + 关键词过滤 ──
    skus = parse_api_skus(api_result)
    skus = _filter_by_keywords(skus, include_keywords)

    rows = []
    for sku in skus:
        row = dict(base)  # 复制一份商品级数据
        # SKU 级数据
        row["SKUID"]     = _safe_str(sku.get("sku_id"))
        row["SKU名称"]   = _safe_str(sku.get("sku_name"))
        row["SKU图片链接"] = _safe_str(sku.get("sku_image_url"))
        row["实际售价"]   = _safe_str(sku.get("real_price"))
        row["原价"]      = _safe_str(sku.get("original_price"))
        row["活动价格"]   = _safe_str(sku.get("activity_price"))
        row["数据来源"] = "api"
        rows.append(row)

    # 兜底：无 SKU 时从接口商品级价格补
    if not rows:
        row = dict(base)
        row["SKUID"]     = ""
        row["SKU名称"]   = ""
        row["SKU图片链接"] = ""
        # 从 API 响应取商品级价格
        data = _api_data(api_result)
        price_val = _safe_str(data.get("price") or "")
        # 新格式价格也是分
        if price_val and len(price_val) > 3 and "." not in price_val:
            try: price_val = str(float(price_val) / 100)
            except Exception: pass
        row["实际售价"]   = price_val
        row["原价"]      = price_val
        row["活动价格"]   = ""
        row["数据来源"] = "api"
        rows.append(row)

    return json.dumps(rows, ensure_ascii=False)


# ============================================================
# 影刀入口
# ============================================================

def main(product_id: str, product_name: str, shop_name: str,
         main_image_url: str, sales: str, crawl_time: str,
         api_result, include_keywords=None) -> str:
    """
    影刀入口 — 返回 13 列 SKU 行 JSON 字符串

    参数:
        include_keywords : 关键词列表（可选），如 ["少年版","标准版"]
                           JSON 字符串或 Python list；仅保留 SKU 名称含任意关键词的 SKU
                           空/None → 不过滤
    """
    # 自动提取 response
    if isinstance(api_result, dict) and "response" in api_result:
        api_result = api_result["response"]
    elif isinstance(api_result, str):
        api_result = json.loads(api_result)
        if isinstance(api_result, dict) and "response" in api_result:
            api_result = api_result["response"]

    # ── 下架/未上架/异常响应：data 是字符串提示语（如"商品已经下架"）而非对象 ──
    # 策略（2026-10-08 定）：只保流程不中断——流程日志记一行原因，返回空数组，不写数据银行
    if not isinstance(api_result, dict) or not isinstance(api_result.get("data"), dict):
        if isinstance(api_result, dict) and isinstance(api_result.get("data"), str):
            reason = api_result["data"]
        else:
            reason = "接口返回异常"
        _xbot_log(f"商品 {product_id} 无SKU数据（{reason}），跳过")
        return "[]"

    # 销量为空时从接口补
    if not sales or not str(sales).strip():
        data = _api_data(api_result)
        sales = _safe_str(data.get("totalCount") or data.get("num") or "")

    product_info = {
        "product_id":    _safe_str(product_id),
        "product_name":  _safe_str(product_name),
        "shop_name":     _safe_str(shop_name),
        "main_image_url": _safe_str(main_image_url),
        "sales":         _safe_str(sales),
        "crawl_time":    _safe_str(crawl_time),
    }
    return format_rows(product_info, api_result, include_keywords)


# ============================================================
# 本地调试
# ============================================================
if __name__ == "__main__":
    # 模拟一段 JustOneAPI 返回的 JSON
    demo_api_response = {
        "code": 0,
        "data": {
            "item": {
                "sku_base": [
                    {
                        "skuId": "5095300330629",
                        "propPath": "21433:21373;1627207:23023534496",
                        "price": "199",
                        "promotion_price": "79.9",
                        "activity_price": None,
                        "quantity": "0"
                    },
                    {
                        "skuId": "4556854559028",
                        "propPath": "21433:21373;1627207:8850085755",
                        "price": "169",
                        "promotion_price": "59.9",
                        "activity_price": None,
                        "quantity": "200"
                    }
                ],
                "sku_props": [
                    {
                        "pid": "21433",
                        "name": "尺寸",
                        "values": [
                            {"vid": "21373", "name": "14寸"},
                            {"vid": "12563493", "name": "15.6寸"}
                        ]
                    },
                    {
                        "pid": "1627207",
                        "name": "颜色分类",
                        "values": [
                            {"vid": "23023534496", "name": "【各版本区别说明】"},
                            {"vid": "8850085755", "name": "深空灰—四大隔层【标准版】"}
                        ]
                    }
                ],
                "sku_images": {
                    "1627207:23023534496": "//img.alicdn.com/i2/O1CN01vikO281nb3VQpnrXS_!!1782885107.png",
                    "1627207:8850085755": "//img.alicdn.com/i2/O1CN01A3PXgv1nb3KvgweUE_!!1782885107.jpg"
                }
            }
        }
    }

    json_output = main(
        product_id="620210933491",
        product_name="笔记本电脑包16寸",
        shop_name="Structure数码自营店",
        main_image_url="https://img.example.com/main.jpg",
        sales="9000",
        crawl_time="2026-07-18 14:30:00",
        api_result=demo_api_response,
    )
    print(json_output)
