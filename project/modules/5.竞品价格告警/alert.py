"""
============================================================
④ 竞品数据反馈 — 价格预警
============================================================
作用：查 MySQL 数据库 → 两段规则判断 → 直发钉钉群通知

两段预警：
  ① 历史新低 — 今日实际售价 < 历史最低价（排除今日自身）
     级别：紧急  |  互斥：命中后不再触发②

  ② 昨日降价 — 今日实际售价 < 昨日实际售价，且降幅 > 阈值
     级别：警告  |  默认阈值 5%

数据库查询：
  competitor_sku（今日快照）
    JOIN competitor_product（取商品名）
    LEFT JOIN price_history（昨日最新价 + 历史最低价）

调用方式：
  影刀：alert.main(config_path, webhook_url, keyword, drop_pct)
  本地：python alert.py（需改 __main__ 中的 token）
============================================================
"""

import json
import os
from datetime import date, datetime, timedelta

import pymysql
import requests


# ============================================================
# 工具函数
# ============================================================

def _abspath(path):
    """规范化路径"""
    return os.path.normpath(os.path.abspath(str(path).strip().strip("\"'")))


def _load_json(path):
    """读取 JSON 文件，不存在返回空 dict"""
    path = _abspath(path)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _connect(config_path):
    """从 database.json 读取配置并连接 MySQL"""
    cfg = _load_json(config_path)
    return pymysql.connect(
        host=cfg.get("host", "127.0.0.1"),
        port=cfg.get("port", 3306),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
    )


def _to_float(value):
    """安全转 float：None / 非数字 → None"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ============================================================
# 数据库查询
# ============================================================

def fetch_alert_data(config_path):
    """
    查询今日所有 SKU 的价格对比数据

    返回 list[dict]，每个元素包含：
      product_id      — 商品ID
      product_name    — 商品名称
      sku_name        — SKU名称
      today_price     — 今日实际售价（来自 competitor_sku.sku_price）
      yesterday_price — 昨日最新价（来自 price_history，当天最后一次采集）
      history_lowest  — 历史最低价（来自 price_history，排除今日）
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    conn = _connect(config_path)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            sql = """
                SELECT
                    p.product_id,
                    p.product_name,
                    s.sku_name,
                    s.sku_price   AS today_price,
                    y.price       AS yesterday_price,
                    (
                        SELECT MIN(h.price)
                        FROM price_history h
                        WHERE h.product_id = s.product_id
                          AND h.sku_name   = s.sku_name
                          AND h.price IS NOT NULL
                          AND h.crawl_date < %s
                    ) AS history_lowest
                FROM competitor_sku s
                JOIN competitor_product p
                    ON s.product_id = p.product_id
                LEFT JOIN (
                    -- 子查询：取昨日每个 SKU 的最新价格
                    SELECT h1.product_id, h1.sku_name, h1.price
                    FROM price_history h1
                    INNER JOIN (
                        SELECT product_id, sku_name,
                               MAX(crawl_time) AS max_time
                        FROM price_history
                        WHERE crawl_date = %s
                        GROUP BY product_id, sku_name
                    ) h2 ON h1.product_id = h2.product_id
                        AND h1.sku_name   = h2.sku_name
                        AND h1.crawl_time = h2.max_time
                    WHERE h1.crawl_date = %s
                ) y ON s.product_id = y.product_id
                    AND s.sku_name   = y.sku_name
                ORDER BY p.product_id, s.sku_name
            """
            # 三个 %s 依次对应：历史最低的日期过滤、昨日最大时间的日期、
            #                   昨日价格的日期（与上面同一个 yesterday）
            cur.execute(sql, (today, yesterday, yesterday))
            return cur.fetchall()
    finally:
        conn.close()


# ============================================================
# 两段预警规则
# ============================================================

def check_alerts(rows, drop_pct=5.0):
    """
    对查询结果逐行执行两段预警

    参数:
        rows     : fetch_alert_data() 返回的列表
        drop_pct : 降价阈值（百分比），默认 5 表示降幅 > 5% 才触发

    返回 list[dict]:
        {
          "type": "new_lowest" | "price_drop",
          "level": "紧急" | "警告",
          "product": "商品名", "sku": "SKU名",
          "today_price": 69.9, "yesterday_price": 79.9,
          "history_lowest": 79.9, "percent": 12.5
        }
    """
    alerts = []

    for row in rows:
        product = row.get("product_name") or row.get("product_id") or ""
        sku = row.get("sku_name") or ""
        today = _to_float(row.get("today_price"))
        yesterday = _to_float(row.get("yesterday_price"))
        hist_low = _to_float(row.get("history_lowest"))

        # 今日无价格 → 跳过
        if today is None:
            continue

        # ---- 预警①：历史新低 ----
        # 条件：今日价 < 历史最低价（且历史最低价存在）
        if hist_low is not None and today < hist_low:
            pct = round((hist_low - today) / hist_low * 100, 1)
            alerts.append({
                "type": "new_lowest",
                "level": "紧急",
                "product": product,
                "sku": sku,
                "today_price": today,
                "yesterday_price": yesterday,
                "history_lowest": hist_low,
                "percent": pct,
            })
            # 历史新低本身已是降价，不再重复触发"昨日降价"
            continue

        # ---- 预警②：昨日降价 ----
        # 条件：有昨日价格 且 昨日价 > 0 且 降幅 > 阈值
        if yesterday is not None and yesterday > 0:
            drop_rate = (yesterday - today) / yesterday
            if drop_rate * 100 > drop_pct:
                pct = round(drop_rate * 100, 1)
                alerts.append({
                    "type": "price_drop",
                    "level": "警告",
                    "product": product,
                    "sku": sku,
                    "today_price": today,
                    "yesterday_price": yesterday,
                    "history_lowest": hist_low,
                    "percent": pct,
                })

    return alerts


# ============================================================
# 钉钉 Markdown 拼装
# ============================================================

def _build_markdown(alerts, keyword=""):
    """
    拼钉钉 markdown 格式的消息正文

    钉钉 markdown 支持的语法：
      ## 标题
      **粗体**
      > 引用块（灰色背景）
    """
    kw_str = f" · {keyword}" if keyword else ""
    title = f"竞品价格预警{kw_str} 共 {len(alerts)} 条"

    lines = [f"## {title}", ""]

    for i, alert in enumerate(alerts, 1):
        if alert["type"] == "new_lowest":
            lines.append(
                f"**{i}. 历史新低**\n\n"
                f"> 商品：{alert['product']}\n\n"
                f"> SKU：{alert['sku']}\n\n"
                f"> 历史最低：{alert['history_lowest']} → "
                f"今日：**{alert['today_price']}**\n\n"
                f"> 降幅：{alert['percent']}%\n"
            )
        else:
            lines.append(
                f"**{i}. 价格下降 {alert['percent']}%**\n\n"
                f"> 商品：{alert['product']}\n\n"
                f"> SKU：{alert['sku']}\n\n"
                f"> 昨日：{alert['yesterday']} → "
                f"今日：**{alert['today_price']}**\n"
            )

    return title, "\n".join(lines)


# ============================================================
# 钉钉发送
# ============================================================

def send_dingtalk(alerts, webhook_url, keyword=""):
    """
    通过钉钉机器人 Webhook 发送预警消息

    参数:
        alerts      : check_alerts() 返回的预警列表
        webhook_url : 钉钉机器人 Webhook URL
        keyword     : 搜索关键词（拼到标题）

    返回:
        {"ok": True, "sent": N}  或  {"ok": False, "error": "..."}
    """
    if not alerts:
        return {"ok": True, "sent": 0, "message": "无预警"}

    title, text = _build_markdown(alerts, keyword=keyword)

    try:
        resp = requests.post(
            webhook_url,
            json={
                "msgtype": "markdown",
                "markdown": {"title": title, "text": text},
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()

        # 钉钉返回 errcode=0 表示成功
        if result.get("errcode") == 0:
            return {"ok": True, "sent": len(alerts)}

        return {"ok": False, "error": f"钉钉返回错误: {result}"}

    except requests.RequestException as e:
        return {"ok": False, "error": f"请求失败: {e}"}


# ============================================================
# 主入口
# ============================================================

def run(config_path, webhook_url, keyword="", drop_pct=5.0):
    """
    完整执行：查库 → 预警判断 → 发钉钉

    返回: {"ok": True, "alert_count": N, "sent": N, ...}
    """
    # 1. 查库
    rows = fetch_alert_data(config_path)

    # 2. 预警判断
    alerts = check_alerts(rows, drop_pct=drop_pct)

    # 3. 无预警直接返回
    if not alerts:
        return {"ok": True, "alert_count": 0, "sent": 0, "message": "无预警"}

    # 4. 发钉钉
    result = send_dingtalk(alerts, webhook_url, keyword=keyword)
    result["alert_count"] = len(alerts)
    return result


def _safe_path(p):
    """修复影刀传参时被 Python 转义的路径（如 \1 → \x01，还原为 \1）"""
    if p is None:
        return None
    s = str(p)
    for i in range(1, 10):
        s = s.replace(chr(i), '\\' + str(i))
    s = s.replace('\r', '\\r')
    s = s.replace('\n', '\\n')
    s = s.replace('\f', '\\f')
    s = s.replace('\v', '\\v')
    return s


def main(config_path, webhook_url, keyword="", drop_pct=5.0):
    """
    影刀入口函数

    参数:
        config_path : database.json 绝对路径
        webhook_url : 钉钉机器人 Webhook URL（必传）
        keyword     : 搜索关键词（可选，拼标题）
        drop_pct    : 降价阈值 %（默认 5，即降幅超过 5% 触发）

    返回:
        {"ok": True, "alert_count": N, "sent": N}
    """
    config_path = _safe_path(config_path)
    return run(
        config_path,
        webhook_url=webhook_url,
        keyword=keyword,
        drop_pct=float(drop_pct) if drop_pct else 5.0,
    )


# ============================================================
# 本地调试
# ============================================================
if __name__ == "__main__":
    # 计算项目根目录（本文件在 project/modules/4.竞品数据汇总/ 下，往上 3 层）
    MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(MODULE_DIR)))

    CONFIG = os.path.join(PROJECT_DIR, "project", "config", "database.json")
    WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=你的token"

    result = run(CONFIG, WEBHOOK, keyword="小天才Z6pro", drop_pct=5.0)
    print(json.dumps(result, ensure_ascii=False, indent=2))
