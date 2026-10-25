"""
============================================================
② SKU 数据采集 — API 调用模块
============================================================
作用：根据商品 ID 调用 JustOneAPI，返回原始响应（给 api_to_datatable 解析）

配置读 config/api_config.json（token 永不入库），版本自动轮转 v9→v5→v4→v1

调用方式（影刀）：
  result = api.main(商品ID)                 # 不传配置路径，自动定位
  result = api.main(商品ID, config_path)    # 或画布显式传参，与 database.json 同款约定
  if result["ok"]:
      原始JSON = result["response"]   # 传给 api_to_datatable
  else:
      走网页兜底分支
============================================================
"""

import json
import os
import time
import random

import requests

try:
    from xbot import print  # 影刀运行时：print 转进运行日志面板；本地调试回退内置 print
except ImportError:
    pass

# ---- 配置外置：token/base_url/轮转参数一律从 api_config.json 读，不落代码 ----
# 候选顺序：画布显式 config_path → __file__ 相对（仓库内调试）→ 仓库绝对路径
# （影刀跑的是应用内副本，__file__ 不在仓库，靠第三个候选兜底）
_CONFIG_CANDIDATES = [
    os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir, os.pardir, "config", "api_config.json")),
    r"F:/Programs/RPA自动化/1-淘宝竞品价格监控自动化/project/config/api_config.json",
]


def _load_config(config_path=""):
    for p in ([config_path] if config_path else []) + _CONFIG_CANDIDATES:
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        "找不到 api_config.json：token/base_url 只从配置文件读取，不落代码")


def _call_api(product_id, version, cfg):
    """调用指定版本的 API，返回原始响应 JSON 或 None"""
    url = (f"{cfg['base_url']}/api/taobao/get-item-detail/{version}"
           f"?token={cfg['token']}&itemId={product_id}")
    max_retries = int(cfg.get("max_retries", 3))

    for attempt in range(max_retries + 1):
        try:
            result = requests.get(url, timeout=float(cfg.get("timeout_sec", 180))).json()
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

        if attempt < max_retries:
            delay = min(1.0 * (2 ** attempt), 30.0)
            jitter = random.uniform(-0.25, 0.25) * delay
            wait_sec = max(0.5, delay + jitter)
            print(f"[api] 重试等待 {wait_sec:.1f}s ...")
            time.sleep(wait_sec)

    return None


def main(product_id: str, config_path: str = "") -> dict:
    """
    调用 JustOneAPI（版本轮转 + 网络重试 + 自动延迟）

    参数:
        product_id  : 淘宝商品数字 ID
        config_path : api_config.json 路径（画布可选传参；不传则自动定位）

    返回:
        成功 → {"ok": True,  "product_id": "...", "skus": [...]}
        失败 → {"ok": False, "product_id": "...", "error": "..."}
    """
    cfg = _load_config(config_path)

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
    for version in (cfg.get("detail_versions") or ["v9", "v5", "v4", "v1"]):
        print(f"[api] 尝试版本 {version}")
        try:
            data = _call_api(product_id, version, cfg)
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
