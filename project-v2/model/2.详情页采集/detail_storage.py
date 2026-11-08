"""详情页落盘（见 §2.4e）：

  runtime/v2/detail_json/<product_id>/<YYYYMMDD>.json      正常：ICE JSON 原文
  runtime/v2/detail_html/<product_id>/<YYYYMMDD>.html.gz   异常：整页 HTML
  runtime/v2/detail_raw/<YYYYMMDD_HHMM>.jsonl              解析结果（一行一个 SKU）
  runtime/v2/run_log/<YYYYMMDD_HHMM>_detail.json           本轮台账

纪律与列表采集一致：原子写、JSONL 追加、回读校验。
"""

import os
import sys

# 影刀 process.invoke_module 不会把模块目录放进 sys.path；补上才能导入同目录 CodeFlow
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

try:  # 允许脱离影刀离线运行/被本地代码 import
    import xbot
    from xbot import print, sleep
except ImportError:
    xbot = None
try:
    from . import package
    from .package import variables as glv
except ImportError:
    try:
        import package
        from package import variables as glv
    except ImportError:
        package = None
        glv = None

import gzip
import json
import time

DEFAULT_ROOT = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2\runtime"


def _log(msg):
    if xbot is not None:
        try:
            xbot.app.logging.info(msg)
            return
        except Exception:
            pass
    print(msg)


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write_text(path, text):
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)
    return path


def new_run(root=None, ts=None):
    """建本轮目录并返回路径字典。"""
    root = root or DEFAULT_ROOT
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    day = ts.split("_")[0]
    _ensure_dir(os.path.join(root, "detail_json"))
    _ensure_dir(os.path.join(root, "detail_html"))
    _ensure_dir(os.path.join(root, "detail_raw"))
    _ensure_dir(os.path.join(root, "run_log"))
    run = {
        "root": root,
        "ts": ts,
        "day": day,
        "jsonl_path": os.path.join(root, "detail_raw", ts + ".jsonl"),
        "run_log_path": os.path.join(root, "run_log", ts + "_detail.json"),
    }
    _log("[详情落盘] 本轮：%s" % run["jsonl_path"])
    return run


def save_ice(product_id, ice, run):
    """保存 ICE JSON 原文（正常路径必存）。返回 path。"""
    d = _ensure_dir(os.path.join(run["root"], "detail_json", str(product_id)))
    path = os.path.join(d, run["day"] + ".json")
    _atomic_write_text(path, json.dumps(ice, ensure_ascii=False))
    _log("[详情落盘] ICE JSON %s → %s" % (product_id, os.path.basename(path)))
    return path


def save_html_gz(product_id, html, run):
    """异常时保存整页 HTML（gzip）+ 回读校验。返回 (path, ok)。"""
    d = _ensure_dir(os.path.join(run["root"], "detail_html", str(product_id or "unknown")))
    path = os.path.join(d, run["day"] + ".html.gz")
    part = path + ".part"
    with gzip.open(part, "wt", encoding="utf-8", newline="") as f:
        f.write(html)
    os.replace(part, path)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        back = f.read()
    ok = len(back) == len(html)
    _log("[详情落盘] 异常 HTML %s %s" % (product_id, "OK" if ok else "校验失败"))
    return path, ok


def append_rows(rows, run):
    """追加解析结果（一行一个 SKU）。返回累计行数。"""
    if not rows:
        return count_rows(run)
    lines = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)
    with open(run["jsonl_path"], "a", encoding="utf-8", newline="") as f:
        f.write(lines)
        f.flush()
        os.fsync(f.fileno())
    total = count_rows(run)
    _log("[详情落盘] JSONL 追加 %d 条，累计 %d 条" % (len(rows), total))
    return total


def count_rows(run):
    path = run["jsonl_path"]
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def read_rows(run):
    rows = []
    path = run["jsonl_path"]
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def save_run_log(run, meta):
    payload = dict(meta or {})
    payload.setdefault("ts", run["ts"])
    payload.setdefault("jsonl", run["jsonl_path"])
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    _atomic_write_text(run["run_log_path"], text)
    _log("[详情落盘] 台账写入 %s" % os.path.basename(run["run_log_path"]))
    return run["run_log_path"]
