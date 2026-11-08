"""入库总入口：clean/<YYYYMMDD>/ -> MySQL 星型模型。

用法：
  # 建表（幂等，只新增 v2 对象，不动 v1 的 competitor_*）
  python run_ingest.py --date 2026-11-01 --init-schema

  # 正常入库（读 item_reviewed/sku_reviewed 优先）
  python run_ingest.py --date 2026-11-01

  # 演练：完整跑一遍再回滚，不写事实
  python run_ingest.py --date 2026-11-01 --dry-run

  # 测试库
  python run_ingest.py --date 2026-11-01 --database price_monitor_v2_test

消费口径（用户 11-01 定）：
  · 只入 review_status ∈ {auto_pass, approved} 的行
  · pending 不入；rejected 不入；缺主键/缺价的计入 skipped_no_key
  · 优先读 *_reviewed.jsonl（人工复核后的状态在这里生效）
  · 补跑旧日期 -> is_late=1；缺口不插值

事务：一个批次一个事务；失败整体回滚，并在独立事务里留一条 failed 台账。
"""

import argparse
import datetime
import json
import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

import db
import ingest_dim
import ingest_fact
import schema

DEFAULT_CLEAN_ROOT = os.path.normpath(os.path.join(
    _MODULE_DIR, "..", "runtime", "clean"))

OK_STATUS = ("auto_pass", "approved")
BAD_STATUS = ("rejected",)


def _log(msg):
    print(msg)
    sys.stdout.flush()


# ------------------------------------------------------------
# 找目录 / 读文件
# ------------------------------------------------------------
def latest_clean_dir(clean_root):
    best = None
    if not os.path.isdir(clean_root):
        return None
    for name in os.listdir(clean_root):
        if not os.path.isdir(os.path.join(clean_root, name)):
            continue
        iso = _date_from_dir(name)
        if iso and (best is None or iso > best[0]):
            best = (iso, os.path.join(clean_root, name))
    return best[1] if best else None


def _date_from_dir(name):
    s = name.replace("-", "")
    if len(s) == 8 and s.isdigit():
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    return None


def _read(clean_dir, base):
    """优先复核后的文件。返回 (rows, used_file)。"""
    reviewed = os.path.join(clean_dir, base.replace(".jsonl", "_reviewed.jsonl"))
    plain = os.path.join(clean_dir, base)
    path = reviewed if os.path.exists(reviewed) else plain
    if not os.path.exists(path):
        return [], ""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows, os.path.basename(path)


def _status(row):
    return str(row.get("review_status") or "")


def _valid_item(row):
    return bool(row.get("product_id")) and (
        row.get("price_detail") is not None or row.get("price_list") is not None)


def _valid_sku(row):
    return bool(row.get("sku_id")) and bool(row.get("product_id")) and row.get("price") is not None


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def run(args):
    dry = bool(args.get("dry_run"))
    run_date = ingest_fact.to_date(args.get("run_date") or datetime.date.today().isoformat())

    clean_dir = args.get("clean_dir") or ""
    if not clean_dir:
        root = args.get("clean_root") or DEFAULT_CLEAN_ROOT
        date = args.get("date") or ""
        if date:
            clean_dir = os.path.join(root, date.replace("-", ""))
        else:
            clean_dir = latest_clean_dir(root) or ""
    if not clean_dir or not os.path.isdir(clean_dir):
        raise SystemExit("找不到清洗产物目录：%s" % clean_dir)

    date = args.get("date") or _date_from_dir(os.path.basename(clean_dir.rstrip("\\/")))
    if not date:
        raise SystemExit("无法从目录名解析日期，请显式传 --date：%s" % clean_dir)

    items_raw, item_file = _read(clean_dir, "item.jsonl")
    skus_raw, sku_file = _read(clean_dir, "sku.jsonl")
    inv_raw, inv_file = _read(clean_dir, "inventory.jsonl")

    counts = {"item_rows": 0, "sku_rows": 0, "inventory_rows": 0,
              "skipped_pending": 0, "skipped_rejected": 0, "skipped_no_key": 0}
    items, skus, invs = [], [], []

    for r in items_raw:
        st = _status(r)
        if st in BAD_STATUS:
            counts["skipped_rejected"] += 1
        elif st not in OK_STATUS:
            counts["skipped_pending"] += 1
        elif not _valid_item(r):
            counts["skipped_no_key"] += 1
        else:
            items.append(r)

    for r in skus_raw:
        st = _status(r)
        if st in BAD_STATUS:
            counts["skipped_rejected"] += 1
        elif st not in OK_STATUS:
            counts["skipped_pending"] += 1
        elif not _valid_sku(r):
            counts["skipped_no_key"] += 1
        else:
            skus.append(r)

    for r in inv_raw:
        st = _status(r)
        if st in BAD_STATUS:
            counts["skipped_rejected"] += 1
        elif st not in OK_STATUS:
            counts["skipped_pending"] += 1
        elif not (r.get("sku_id") and r.get("product_id")):
            counts["skipped_no_key"] += 1
        else:
            invs.append(r)

    is_late = 1 if ingest_fact.to_date(date) < run_date else 0
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    batch_id = args.get("batch_id") or "v2-%s-%s" % (
        ingest_fact.to_date(date).strftime("%Y%m%d"), ts)

    db_name = args.get("database")
    if not args.get("no_schema"):
        db_name = schema.ensure_database(args.get("config"), db_name)
    conn = db.connect(args.get("config"), db_name)
    try:
        if not args.get("no_schema"):
            schema.ensure(conn, views=not args.get("no_views"))
            conn.commit()

        # 维度：先商品后 SKU。dim 不受复核状态限制（rejected 已在上面排除）
        product_attrs = {}
        for r in items:
            product_attrs.setdefault(r["product_id"], {
                "title": r.get("title") or "",
                "shop_name": r.get("shop_name") or "",
                "platform": r.get("platform") or "",
            })
        for r in skus + invs:
            product_attrs.setdefault(r["product_id"], {
                "title": r.get("title") or "",
                "shop_name": r.get("shop_name") or r.get("shop") or "",
                "platform": r.get("platform") or "",
            })

        dim_actions = {}
        for pid in sorted(product_attrs):
            act = ingest_dim.observe_product(conn, pid, product_attrs[pid], date)
            dim_actions[act] = dim_actions.get(act, 0) + 1
        for r in skus + invs:
            ingest_dim.observe_sku(conn, r, date)

        # 事实
        for r in items:
            ingest_fact.upsert_item(conn, r, batch_id, is_late)
            counts["item_rows"] += 1
        for r in skus:
            ingest_fact.upsert_sku(conn, r, batch_id, is_late)
            counts["sku_rows"] += 1
        for r in invs:
            ingest_fact.upsert_inventory(conn, r, batch_id)
            counts["inventory_rows"] += 1

        batch = {
            "batch_id": batch_id, "crawl_date": date,
            "run_at": datetime.datetime.now(), "source_dir": clean_dir,
            "status": "dry_run" if dry else "ok",
            "note": "files=%s,%s,%s is_late=%d" % (item_file, sku_file, inv_file, is_late),
            **counts,
        }
        ingest_fact.upsert_batch(conn, batch)

        if dry:
            conn.rollback()
        else:
            conn.commit()

        _log("[入库] %s%s | 批次 %s | 来源 %s" % (
            date, "（补跑，is_late=1）" if is_late else "", batch_id,
            os.path.basename(clean_dir.rstrip("\\/"))))
        _log("[入库] 文件：%s / %s / %s" % (item_file or "-", sku_file or "-", inv_file or "-"))
        _log("[入库] 事实：item %(item_rows)d | sku %(sku_rows)d | inventory %(inventory_rows)d"
             % counts)
        _log("[入库] 跳过：pending %(skipped_pending)d | rejected %(skipped_rejected)d | "
             "缺主键 %(skipped_no_key)d" % counts)
        _log("[入库] 维度：%s" % (dim_actions or "无"))
        _log("[入库] %s" % ("已回滚（dry-run）" if dry else "已提交"))
        return {"batch_id": batch_id, "date": date, "is_late": is_late,
                "counts": counts, "dim": dim_actions, "dry_run": dry,
                "database": db.describe(args.get("config"), args.get("database"))}

    except Exception as e:
        conn.rollback()
        _log("[入库] 失败，已回滚：%s: %s" % (type(e).__name__, str(e)[:300]))
        try:
            ingest_fact.upsert_batch(conn, {
                "batch_id": batch_id, "crawl_date": date,
                "run_at": datetime.datetime.now(), "source_dir": clean_dir,
                "status": "failed", "note": "%s: %s" % (type(e).__name__, str(e)[:400]),
                **counts,
            })
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def main(args=None):
    return run(args or {})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v2 数据入库（星型模型）")
    ap.add_argument("--date", default="", help="采集日期 YYYY-MM-DD；默认取最新 clean 目录")
    ap.add_argument("--clean-dir", default="", help="直接指定 clean/<YYYYMMDD> 目录")
    ap.add_argument("--clean-root", default=DEFAULT_CLEAN_ROOT, help="clean 根目录")
    ap.add_argument("--config", default="", help="database.json 路径")
    ap.add_argument("--database", default="", help="覆盖库名（测试库用）")
    ap.add_argument("--run-date", default="", help="运行日（默认今天）；早于运行日即 is_late=1")
    ap.add_argument("--batch-id", default="", help="自定义批次号")
    ap.add_argument("--init-schema", action="store_true", help="只建表/视图，不入数据")
    ap.add_argument("--no-schema", action="store_true", help="不自动建表")
    ap.add_argument("--no-views", action="store_true", help="不建视图")
    ap.add_argument("--dry-run", action="store_true", help="完整执行后回滚")
    args = vars(ap.parse_args())

    if args.get("init_schema"):
        name = schema.ensure_database(args.get("config"), args.get("database"))
        conn = db.connect(args.get("config"), name)
        try:
            tables, views = schema.ensure(conn, views=not args.get("no_views"))
            conn.commit()
            print("[建表] 库 %s | 表 %s | 视图 %s" % (name, tables, views))
        finally:
            conn.close()
    else:
        run(args)
