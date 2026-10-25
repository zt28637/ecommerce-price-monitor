"""
============================================================
④ 竞品数据反馈 — 价格预警
============================================================
作用：查 MySQL 数据库 → 两段规则判断 → 直发钉钉群通知

两段预警：
  ① 历史新低 — 今日实际售价 < 历史最低价（排除今日自身）
     级别：紧急  |  互斥：命中后不再触发②

  ② 降价预警 — 今日实际售价 < 上一次快照价（该 SKU 今天之前最近一次采集，
     不是"日历昨天"——断跑几天也对齐最近一次），且降幅 > 阈值
     级别：警告  |  默认阈值 5%

数据库查询：
  competitor_sku（今日快照 = WHERE DATE(crawl_time)=今日；该表本身是
    upsert 累积表，含历史下架商品的陈旧行，不过滤会把旧价当今日价误报）
    JOIN competitor_product（取商品名）
    LEFT JOIN price_history（上次快照价 + 历史最低价，均排除今日）

调用方式：
  影刀：alert.main(config_path, webhook_url, keyword, drop_pct)
  本地：python alert.py（需改 __main__ 中的 token）
============================================================
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import date

import pymysql
import requests

try:
    from xbot import print  # 影刀运行时：print 转进运行日志面板；本地调试回退内置 print
except ImportError:
    pass


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
      last_price      — 上一次快照价（price_history 中该 SKU 今天之前最近一次采集；
                        断跑多日也对齐"上一快照"，不是"日历昨天"）
      last_date       — 上一快照所在采集日期（消息里标注，避免隔多日误读）
      history_lowest  — 历史最低价（来自 price_history，排除今日）
    """
    today = date.today()

    conn = _connect(config_path)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            sql = """
                SELECT
                    p.product_id,
                    p.product_name,
                    s.sku_name,
                    s.sku_price   AS today_price,
                    y.price       AS last_price,
                    y.crawl_date  AS last_date,
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
                    -- 子查询：取每个 SKU "今天之前最近一次"采集的价格（上一快照）
                    -- 用 < today 而非 = 昨天：断跑 N 天仍对齐真实上一次，预警不漏
                    -- ROW_NUMBER 去重：同批插入的多行 crawl_time 完全相同，
                    -- MAX(crawl_time) 自连接会翻倍出重复预警（2026-10-25 实测 119→128）
                    SELECT product_id, sku_name, price, crawl_date
                    FROM (
                        SELECT h1.product_id, h1.sku_name, h1.price, h1.crawl_date,
                               ROW_NUMBER() OVER (
                                   PARTITION BY h1.product_id, h1.sku_name
                                   ORDER BY h1.crawl_time DESC, h1.id DESC
                               ) AS rn
                        FROM price_history h1
                        WHERE h1.crawl_date < %s
                    ) x
                    WHERE rn = 1
                ) y ON s.product_id = y.product_id
                    AND s.sku_name   = y.sku_name
                -- competitor_sku 是 upsert 累积表（下架商品永不删除），
                -- 必须按 crawl_time 圈定"今日真实采集"，否则拿两个月前的
                -- 陈旧快照当今日价，幽灵降价全涌进预警（2026-10-25 实测）
                WHERE DATE(s.crawl_time) = %s
                ORDER BY p.product_id, s.sku_name
            """
            # 三个 %s 都绑 today（按 SQL 文本中出现顺序）：
            #   ①历史最低排今日 ②上次快照=今日前最近一条 ③圈定今日采集
            cur.execute(sql, (today, today, today))
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
          "product": "商品名", "product_id": "商品ID", "sku": "SKU名",
          "today_price": 69.9, "last_price": 79.9, "last_date": date | None,
          "history_lowest": 79.9, "percent": 12.5
        }
    """
    alerts = []

    for row in rows:
        product = row.get("product_name") or row.get("product_id") or ""
        sku = row.get("sku_name") or ""
        today = _to_float(row.get("today_price"))
        last = _to_float(row.get("last_price"))
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
                "product_id": row.get("product_id") or "",
                "sku": sku,
                "last_date": row.get("last_date"),
                "today_price": today,
                "last_price": last,
                "history_lowest": hist_low,
                "percent": pct,
            })
            # 历史新低本身已是降价，不再重复触发"降价预警"
            continue

        # ---- 预警②：降价预警（vs 上一次快照） ----
        # 条件：有上次快照价 且 > 0 且 降幅 > 阈值
        if last is not None and last > 0:
            drop_rate = (last - today) / last
            if drop_rate * 100 > drop_pct:
                pct = round(drop_rate * 100, 1)
                alerts.append({
                    "type": "price_drop",
                    "level": "警告",
                    "product": product,
                    "product_id": row.get("product_id") or "",
                    "sku": sku,
                    "last_date": row.get("last_date"),
                    "today_price": today,
                    "last_price": last,
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
        # "上次"标注日期：断跑多日后避免被误读成"昨天刚降"
        pid_line = f"> 商品ID：{alert.get('product_id', '')}\n\n" if alert.get("product_id") else ""
        last_date = alert.get("last_date")
        date_tag = f"（{last_date}）" if last_date else ""

        if alert["type"] == "new_lowest":
            lines.append(
                f"**{i}. 历史新低**\n\n"
                f"> 商品：{alert['product']}\n\n"
                f"{pid_line}"
                f"> SKU：{alert['sku']}\n\n"
                f"> 历史最低：{alert['history_lowest']} → "
                f"今日：**{alert['today_price']}**\n\n"
                f"> 降幅：{alert['percent']}%\n"
            )
        else:
            lines.append(
                f"**{i}. 价格下降 {alert['percent']}%**\n\n"
                f"> 商品：{alert['product']}\n\n"
                f"{pid_line}"
                f"> SKU：{alert['sku']}\n\n"
                f"> 上次{date_tag}：{alert['last_price']} → "
                f"今日：**{alert['today_price']}**\n"
            )

    return title, "\n".join(lines)


# ============================================================
# 钉钉发送
# ============================================================

def _signed_url(webhook_url, secret=""):
    """钉钉「加签」安全模式：URL 追加 timestamp+sign（官方 HMAC-SHA256 算法）。

    不传 secret 则原样返回 —— 对应「自定义关键词」模式的机器人
    （该模式下 keyword 须命中机器人所设关键词，否则被钉钉拒收 errcode 310000）。

    影刀全局变量常见脏值：粘贴时连引号一起带入（'"https://…"'）→ 先剥掉。
    """
    webhook_url = str(webhook_url).strip().strip("\"'")
    secret = str(secret).strip().strip("\"'")
    if not secret:
        return webhook_url
    ts = str(round(time.time() * 1000))
    digest = hmac.new(secret.encode("utf-8"),
                      f"{ts}\n{secret}".encode("utf-8"),
                      hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    return f"{webhook_url}&timestamp={ts}&sign={sign}"


def send_dingtalk(alerts, webhook_url, keyword="", secret=""):
    """
    通过钉钉机器人 Webhook 发送预警消息

    参数:
        alerts      : check_alerts() 返回的预警列表
        webhook_url : 钉钉机器人 Webhook URL
        keyword     : 搜索关键词（拼到标题；「关键词模式」还须命中）
        secret      : 机器人「加签」密钥（SEC… 开头）；关键词模式留空

    返回:
        {"ok": True, "sent": N}  或  {"ok": False, "error": "..."}
    """
    if not alerts:
        return {"ok": True, "sent": 0, "message": "无预警"}

    title, text = _build_markdown(alerts, keyword=keyword)

    try:
        resp = requests.post(
            _signed_url(webhook_url, secret),
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

def run(config_path, webhook_url, keyword="", secret="", drop_pct=5.0):
    """
    完整执行：查库 → 预警判断 → 发钉钉

    返回: {"ok": True, "alert_count": N, "sent": N, ...}
    """
    # 1. 查库
    rows = fetch_alert_data(config_path)
    print(f"[alert] 查库完成：今日 SKU 快照 {len(rows)} 行")

    # 2. 预警判断
    alerts = check_alerts(rows, drop_pct=drop_pct)
    n_low = sum(1 for a in alerts if a["type"] == "new_lowest")
    n_drop = sum(1 for a in alerts if a["type"] == "price_drop")
    print(f"[alert] 预警判断：共 {len(alerts)} 条（历史新低 {n_low} / 降价 {n_drop}）")

    # 3. 无预警直接返回
    if not alerts:
        print("[alert] 无预警，不发送")
        return {"ok": True, "alert_count": 0, "sent": 0, "message": "无预警"}

    # 4. 发钉钉（只记成功与否，不记消息内容与 webhook）
    result = send_dingtalk(alerts, webhook_url, keyword=keyword, secret=secret)
    result["alert_count"] = len(alerts)
    if result.get("ok"):
        print(f"[alert] 钉钉发送成功：{result.get('sent', 0)} 条")
    else:
        print(f"[alert] 钉钉发送失败：{result.get('error', '')}")
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


def main(config_path, webhook_url, keyword="", secret="", drop_pct=5.0):
    """
    影刀入口函数

    参数:
        config_path : database.json 绝对路径
        webhook_url : 钉钉机器人 Webhook URL（必传，glv['dingtalk_webhook']）
        keyword     : 搜索关键词（拼标题；关键词模式下须命中机器人关键词）
        secret      : 钉钉机器人「加签」密钥（glv['dingtalk_secret']）；关键词模式留空
        drop_pct    : 降价阈值 %（默认 5，即降幅超过 5% 触发）

    返回:
        {"ok": True, "alert_count": N, "sent": N}
    """
    config_path = _safe_path(config_path)
    return run(
        config_path,
        webhook_url=webhook_url,
        keyword=keyword,
        secret=secret,
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
    # 本地调试用：export ALERT_WEBHOOK=... ALERT_SECRET=...
    # 真值永不写进代码/文档（同一组值在影刀全局变量 glv['dingtalk_webhook'/'dingtalk_secret']）
    WEBHOOK = os.environ.get("ALERT_WEBHOOK", "")
    SECRET = os.environ.get("ALERT_SECRET", "")

    if not WEBHOOK:
        # 防呆：没配环境变量就直说，别让 requests 报 "No connection adapters"
        raise SystemExit("缺少环境变量 ALERT_WEBHOOK / ALERT_SECRET："
                         "export ALERT_WEBHOOK='https://oapi.dingtalk.com/...' ALERT_SECRET='SEC...'")

    if os.environ.get("ALERT_SMOKE") == "1":
        # 接口冒烟：不查库，用伪造预警直发一条（专测 webhook/加签/关键词三关）
        fake = [{"type": "new_lowest", "level": "紧急",
                 "product": "[测试] 小天才Z6Pro", "product_id": "826399795851",
                 "last_date": None, "sku": "Z6Pro_星云粉",
                 "today_price": 899.0, "last_price": 999.0,
                 "history_lowest": 999.0, "percent": 10.0}]
        print(json.dumps(send_dingtalk(fake, WEBHOOK, keyword="小天才Z6pro",
                                       secret=SECRET), ensure_ascii=False))
    else:
        # 完整链路：查库→判断→发送（库里当天无降价时 sent=0 属正常，不代表接口坏）
        result = run(CONFIG, WEBHOOK, keyword="小天才Z6pro", secret=SECRET,
                     drop_pct=5.0)
        print(json.dumps(result, ensure_ascii=False, indent=2))
