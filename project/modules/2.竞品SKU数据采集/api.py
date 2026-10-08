"""
============================================================
② SKU 数据采集 — API 调用模块
============================================================
作用：根据商品 ID 调用 JustOneAPI，返回原始响应（给 api_to_datatable 解析）

配置硬编码，版本自动轮转 v9→v5→v4→v1

调用方式（影刀）：
  result = api.main(商品ID)
  if result["ok"]:
      原始JSON = result["response"]   # 传给 api_to_datatable
  else:
      走网页兜底分支
============================================================
"""

import json
import time
import random

import requests

# ---- 硬编码配置 ----
_BASE_URL = "https://api.justoneapi.com"
_TOKEN = "<REDACTED>"
_TIMEOUT = 180
_VERSIONS = ["v9", "v5", "v4", "v1"]
_MAX_RETRIES = 3


def _call_api(product_id, version):
    """调用指定版本的 API，返回原始响应 JSON 或 None"""
    url = (f"{_BASE_URL}/api/taobao/get-item-detail/{version}"
           f"?token={_TOKEN}&itemId={product_id}")

    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = requests.get(url, timeout=_TIMEOUT).json()
            data = result.get("data")
            # 闸门必须是"非空对象"：v9 对部分在售商品误报 data="商品已经下架"（字符串 truthy），
            # 旧写法 `and result.get("data")` 会让假话直接短路版本轮转（2026-10-08 实测）
            if result.get("code") in (0, "0") and isinstance(data, dict) and data:
                return result  # 返回完整响应，给 api_to_datatable 解析
            # 业务错误不重试；字符串提示语（下架/不存在）继续轮转下一版本验证
            print(f"[api] {version} 业务失败: code={result.get('code')} data型={type(data).__name__}")
            return None
        except requests.Timeout:
            print(f"[api] {version} 超时 (尝试 {attempt + 1})")
        except requests.ConnectionError as e:
            print(f"[api] {version} 连接失败 (尝试 {attempt + 1}): {e}")
        except requests.RequestException as e:
            print(f"[api] {version} 网络异常 (尝试 {attempt + 1}): {e}")

        if attempt < _MAX_RETRIES:
            delay = min(1.0 * (2 ** attempt), 30.0)
            jitter = random.uniform(-0.25, 0.25) * delay
            wait_sec = max(0.5, delay + jitter)
            print(f"[api] 重试等待 {wait_sec:.1f}s ...")
            time.sleep(wait_sec)

    return None


def main(product_id: str) -> dict:
    """
    调用 JustOneAPI（版本轮转 + 网络重试 + 自动延迟）

    参数:
        product_id : 淘宝商品数字 ID

    返回:
        成功 → {"ok": True,  "product_id": "...", "skus": [...]}
        失败 → {"ok": False, "product_id": "...", "error": "..."}
    """
    # ---- 节奏控制 ----
    delay = random.uniform(2, 5)
    print(f"[api] 等待 {delay:.1f}s ...")
    time.sleep(delay)

    # ---- 参数校验 ----
    product_id = str(product_id).strip()
    if not product_id:
        return {"ok": False, "product_id": "", "error": "商品ID为空"}

    print(f"[api] 商品ID={product_id}")

    # ---- 版本轮转 ----
    for version in _VERSIONS:
        print(f"[api] 尝试版本 {version}")
        try:
            data = _call_api(product_id, version)
        except Exception as e:
            print(f"[api] {version} 异常: {e}")
            continue

        if data is not None:
            print(f"[api] 成功: version={version}")
            return {"ok": True, "response": data}

    print(f"[api] 全部版本失败")
    return {"ok": False, "error": "API全部版本失败"}


# ============================================================
# 本地调试
# ============================================================
if __name__ == "__main__":
    result = main("690987654321")
    print(json.dumps(result, ensure_ascii=False, indent=2))
