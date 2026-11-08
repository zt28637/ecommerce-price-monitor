"""维度入库：dim_product（SCD2）+ dim_sku。

为什么商品要 SCD2：商家改标题/改店铺/换平台后，旧事实仍应能对上**当时**的属性。
如果直接覆盖，历史报表会把"改过名"的商品整段算到新名下。
SKU 不版本化（规格组合名只影响展示），按计划 §5.1 保持单行。

更新策略：
  · 属性没变      → 只推进 last_seen_date
  · 属性变了      → 关掉当前版本（valid_to=前一天，is_current=0），追加新版本
  · 同一天改属性  → 原地改当前版本（同一天不该产生两个版本）
  · 补跑旧日期    → 在时间轴中间插入版本，并把被切开的那段 valid_to 改掉
"""

import datetime

# 平台为空时沿用上一版本，避免 detail_only 行把 tmall 覆盖成 unknown
EMPTY_PLATFORM = ("", "unknown")


def to_date(text):
    s = str(text or "").strip()
    if not s:
        return None
    return datetime.date.fromisoformat(s[:10])


def _fetch(cur, product_id):
    cur.execute("""
        SELECT version_no, title, shop_name, platform,
               valid_from, valid_to, is_current, first_seen_date, last_seen_date
        FROM dim_product WHERE product_id = %s
        ORDER BY valid_from, version_no
    """, (product_id,))
    return list(cur.fetchall())


def _insert(cur, product_id, version_no, attrs, valid_from, valid_to,
            is_current, first_seen, last_seen):
    cur.execute("""
        INSERT INTO dim_product
            (product_id, version_no, title, shop_name, platform,
             valid_from, valid_to, is_current, first_seen_date, last_seen_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (product_id, version_no, attrs["title"], attrs["shop_name"],
          attrs["platform"], valid_from, valid_to, 1 if is_current else 0,
          first_seen, last_seen))


def _same(row, attrs):
    return (row[1] == attrs["title"] and row[2] == attrs["shop_name"]
            and row[3] == attrs["platform"])


def observe_product(conn, product_id, attrs, crawl_date):
    """登记某商品某天的属性。返回 'new' / 'touch' / 'same_day_edit' /
    'new_version' / 'backfill_version' / 'unchanged'。"""
    day = to_date(crawl_date)
    attrs = {
        "title": str(attrs.get("title") or "")[:512],
        "shop_name": str(attrs.get("shop_name") or "")[:256],
        "platform": str(attrs.get("platform") or "")[:16],
    }
    with conn.cursor() as cur:
        rows = _fetch(cur, product_id)

        if not rows:
            if attrs["platform"] in EMPTY_PLATFORM:
                attrs["platform"] = "unknown"
            _insert(cur, product_id, 1, attrs, day, None, True, day, day)
            return "new"

        current = next((r for r in rows if r[6] == 1), rows[-1])
        if attrs["platform"] in EMPTY_PLATFORM and current[3]:
            attrs["platform"] = current[3]

        if _same(current, attrs):
            # 属性没变：只推进观测区间。补跑更早日期时，把「最早版本」的
            # valid_from 往前推（属性相同，不该凭空多一个版本）。
            extend_from = (day < current[4] and current[0] == rows[0][0])
            if extend_from:
                cur.execute("""
                    UPDATE dim_product
                    SET valid_from = %s,
                        first_seen_date = LEAST(first_seen_date, %s),
                        last_seen_date = GREATEST(last_seen_date, %s)
                    WHERE product_id = %s AND version_no = %s
                """, (day, day, day, product_id, current[0]))
            else:
                cur.execute("""
                    UPDATE dim_product
                    SET first_seen_date = LEAST(first_seen_date, %s),
                        last_seen_date = GREATEST(last_seen_date, %s)
                    WHERE product_id = %s AND version_no = %s
                """, (day, day, product_id, current[0]))
            return "touch"

        if day == current[4]:
            cur.execute("""
                UPDATE dim_product
                SET title = %s, shop_name = %s, platform = %s,
                    last_seen_date = GREATEST(last_seen_date, %s)
                WHERE product_id = %s AND version_no = %s
            """, (attrs["title"], attrs["shop_name"], attrs["platform"],
                  day, product_id, current[0]))
            return "same_day_edit"

        next_no = max(r[0] for r in rows) + 1

        if day > current[4]:
            # 正常向前推进：关旧版，开新版
            cur.execute("""
                UPDATE dim_product SET valid_to = %s, is_current = 0
                WHERE product_id = %s AND version_no = %s
            """, (day - datetime.timedelta(days=1), product_id, current[0]))
            _insert(cur, product_id, next_no, attrs, day, None, True,
                    current[7], day)
            return "new_version"

        # 补跑旧日期：找到日期落在其有效期内的版本，从中间切开
        containing = None
        for r in rows:
            start, end = r[4], r[5]
            if start <= day and (end is None or day <= end):
                containing = r
                break
        if containing is not None:
            if _same(containing, attrs):
                cur.execute("""
                    UPDATE dim_product
                    SET first_seen_date = LEAST(first_seen_date, %s),
                        last_seen_date = GREATEST(last_seen_date, %s)
                    WHERE product_id = %s AND version_no = %s
                """, (day, day, product_id, containing[0]))
                return "unchanged"

            # 如果补跑段落的属性恰好等于「下一版」，不新增版本，直接把下一版
            # 的 valid_from 前移，避免出现两个相邻且相同的版本。
            later = [r for r in rows if r[4] > containing[4]]
            if later and _same(min(later, key=lambda r: r[4]), attrs):
                nxt = min(later, key=lambda r: r[4])
                cur.execute("""
                    UPDATE dim_product
                    SET valid_from = %s,
                        first_seen_date = LEAST(first_seen_date, %s)
                    WHERE product_id = %s AND version_no = %s
                """, (day, day, product_id, nxt[0]))
                cur.execute("""
                    UPDATE dim_product SET valid_to = %s
                    WHERE product_id = %s AND version_no = %s
                """, (day - datetime.timedelta(days=1), product_id, containing[0]))
                return "backfill_merge"

            old_end = containing[5]
            cur.execute("""
                UPDATE dim_product SET valid_to = %s
                WHERE product_id = %s AND version_no = %s
            """, (day - datetime.timedelta(days=1), product_id, containing[0]))
            _insert(cur, product_id, next_no, attrs, day, old_end, False,
                    containing[7], day)
            return "backfill_version"

        # 早于最早版本：属性相同就前移首版；不同才插新版本
        first = rows[0]
        if _same(first, attrs):
            cur.execute("""
                UPDATE dim_product
                SET valid_from = %s,
                    first_seen_date = LEAST(first_seen_date, %s),
                    last_seen_date = GREATEST(last_seen_date, %s)
                WHERE product_id = %s AND version_no = %s
            """, (day, day, day, product_id, first[0]))
            return "backfill_extend"
        _insert(cur, product_id, next_no, attrs, day,
                first[4] - datetime.timedelta(days=1), False, day, day)
        return "backfill_version"


def observe_sku(conn, row, crawl_date):
    """登记 SKU 维度（不版本化）。"""
    day = to_date(crawl_date)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dim_sku
                (sku_id, product_id, prop_names, prop_path,
                 first_seen_date, last_seen_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                product_id     = VALUES(product_id),
                prop_names     = VALUES(prop_names),
                prop_path      = VALUES(prop_path),
                last_seen_date = GREATEST(last_seen_date, VALUES(last_seen_date))
        """, (row["sku_id"], row["product_id"],
              str(row.get("prop_names") or "")[:512],
              str(row.get("prop_path") or "")[:512], day, day))
    return "upsert"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("ingest_dim 由 run_ingest 调用；单元测试请用 --dry-run")
