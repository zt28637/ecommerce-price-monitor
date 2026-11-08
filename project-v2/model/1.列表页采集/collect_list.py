import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE and HERE not in sys.path:
    sys.path.insert(0, HERE)

from collect_list_ready import collect_list_ready, BrowserDown, ReadyFailed
from scroll_to_bottom import scroll_to_bottom, _card_ids
from parse_list import parse_list
from filter_product import filter, load_rules
from storage import RunFile, save_run_log
from next_page import turn_next_page

def main(args=None):
    # 列表页采集：准备 -> [滚动 -> 解析 -> 过滤 -> 落盘 -> 翻页] -> 台账
    if not isinstance(args, dict):
        args = {}
    rules = load_rules()
    max_pages = int(args.get("max_pages")
                    or (rules.get("collect") or {}).get("max_pages") or 3)
    target_n = int(args.get("target_n")
                   or (rules.get("collect") or {}).get("target_n") or 0)
    started = time.time()
    run_ts = time.strftime("%Y%m%d_%H%M%S")

    def _result(**kw):
        """统一出口：补齐统计 + 写台账，任何分支拿到的都是同一套字段。

        数量口径（N = M + P，台账自检不平就说明有一条路没统计到）：
          N raw_n      解析出的卡片总数
          M filtered_m 过滤掉的 = 关键词/价格过滤 + 跨页去重
          P passed_p   最终落盘行数
          K failed_k   失败页数（异常中断记 1，正常 0）
        """
        meta = {
            "ok": False, "reason": "", "detail": "",
            "ts": run_ts, "keyword": rules["keyword"],
            "max_pages": max_pages, "target_n": target_n,
            "pages": 0, "raw_n": 0, "filtered_m": 0, "passed_p": 0,
            "dup_m": 0, "failed_k": 0, "partial_pages": [],
            "path": "", "run_log": "",
        }
        meta.update(kw)
        meta["elapsed"] = round(time.time() - started, 1)
        total_m = meta["filtered_m"] + meta["passed_p"]
        meta["balance"] = ("ok" if total_m == meta["raw_n"]
                           else "mismatch: M+P=%d != N=%d" % (total_m, meta["raw_n"]))
        try:
            meta["run_log"] = save_run_log(meta, ts=run_ts)
        except Exception as e:
            print("台账写入失败（不影响采集结果）：%s" % e)
        if meta["balance"] != "ok":
            print("⚠ 台账不平：%s" % meta["balance"])
        print("[列表] N=%d / M=%d（去重 %d）/ P=%d / K=%d · %s"
              % (meta["raw_n"], meta["filtered_m"], meta["dup_m"],
                 meta["passed_p"], meta["failed_k"], meta["balance"]))
        return meta

    # 浏览器只 attach 登录层拉起的 9223；没起来就明确返回，绝不自己新起未登录的浏览器
    # 进搜索页被拦（未登录 / 滑块 / 访问频繁）同样按 reason 返回，不裸抛
    try:
        page = collect_list_ready()
    except BrowserDown as e:
        print("浏览器不可用：%s" % e)
        return _result(reason="browser_down", detail=str(e), failed_k=1)
    except ReadyFailed as e:
        print("搜索页不可用（%s）：%s" % (e.reason, e.detail))
        return _result(reason=e.reason, detail=e.detail, failed_k=1)

    all_passed, seen = [], set()
    # 没确认到底的页：数据仍可用，只记下来（可能少采）
    partial_pages = []
    raw_n = 0
    filtered_m = 0
    dup_m = 0
    pages_done = 0
    failed_k = 0
    reason = ""
    # 增量落盘句柄：每页写完即 flush，中途异常已采页不丢（见 storage.RunFile）
    sink = RunFile(rules["keyword"])
    path = ""

    try:
        for page_no in range(1, max_pages + 1):
            # 页面滚动：懒加载要把整页卡片都加载出来
            reached = scroll_to_bottom(page, _card_ids)
            if not reached:
                # 没到底 = 可能少采，不是错采；仍解析当前页面，只留一笔记录
                partial_pages.append(page_no)
                print("第%d页未确认到底（可能少采），仍解析当前页面" % page_no)

            # 页面解析
            product_list = parse_list(page.html)
            pages_done += 1
            # 标题 + 价格过滤（规则来自 targets.json）
            passed_list = filter(product_list)
            # 同页 + 跨页去重：淘宝会把推广位重复塞进列表
            new_rows = []
            for r in passed_list:
                if r["product_id"] in seen:
                    continue
                seen.add(r["product_id"])
                new_rows.append(r)

            raw_n += len(product_list)
            filtered_m += len(product_list) - len(new_rows)
            dup_m += len(passed_list) - len(new_rows)
            all_passed += new_rows
            # 先落盘再翻页：这一页的数已经安全了，再去谈下一页
            path = sink.append(new_rows)

            print("第%d页 解析%d 通过%d 新增%d 累计%d" % (
                page_no, len(product_list), len(passed_list), len(new_rows), len(all_passed)))

            # 达到目标数就停
            if target_n and len(all_passed) >= target_n:
                print("达到目标数 %d，停止翻页" % target_n)
                break

            if page_no == max_pages:
                break

            # 翻页：失败必须停，否则会在旧页上重复采集
            turn = turn_next_page(page)
            if not turn["ok"]:
                print("翻页停止：%s" % turn["reason"])
                break
            # 新页可能沿用上一页的底部位置；回到顶部，避免被误判到底
            page.run_js("window.scrollTo(0, 0)")
    except Exception as e:
        # 采集中途炸了：不吞异常，但已落盘的前 N 页保留，如实标出来
        reason = "exception: %s" % e
        failed_k = 1
        print("采集中断（%s）；已落盘 %d 条，文件 %s"
              % (e, sink.rows, path or "未创建"))
    finally:
        sink.close()

    # 落盘：runtime/list_raw/<关键词>/<时间戳>.jsonl（每页追加，断在中途也有前 N 页）
    if not path:
        print("没有可落盘的数据；未到底页 %s" % (partial_pages or "无"))
    else:
        print("落盘 %s（%d 条；页数 %d；未到底页 %s）" % (
            path, sink.rows, pages_done, partial_pages or "无"))

    # 影刀「调用模块」拿这个返回值；本地直接跑也方便看统计
    return _result(
        ok=bool(all_passed) and not reason,
        reason=reason,
        pages=pages_done,
        raw_n=raw_n,
        filtered_m=filtered_m,
        dup_m=dup_m,
        passed_p=len(all_passed),
        failed_k=failed_k,
        partial_pages=partial_pages,
        path=path,
    )


if __name__ == "__main__":
    print(main())
