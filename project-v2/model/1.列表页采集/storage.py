import json
import os
import time

# 数据落盘：project-v2/runtime/list_raw/<关键词>/<时间戳>.jsonl
# JSONL = 一行一个商品，追加/读取都简单，坏一行不影响其它行。
HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(HERE, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2",
]


def _first_dir(candidates, required="model"):
    for p in candidates:
        if not p or not os.path.isdir(p):
            continue
        if required and not os.path.exists(os.path.join(p, required)):
            continue
        return p
    return ""


PROJECT_V2 = _first_dir(_PROJECT_CANDIDATES)
ROOT = (os.path.join(PROJECT_V2, "runtime") if PROJECT_V2 else
        os.path.normpath(os.path.join(HERE, "..", "..", "runtime")))


def _atomic_write_text(path, text):
    """先写 .part 再 os.replace：中途被杀不会留下半个 JSON。"""
    part = path + ".part"
    with open(part, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)
    return path


def save_run_log(meta, root=None, ts=None):
    """本轮台账：runtime/run_log/<ts>_list.json

    对齐详情层 detail_storage.save_run_log —— 每轮留下"原始/过滤/通过/失败"
    和水位，事后能回答"这一轮为什么只有 37 条"，而不是只剩一行 print。
    """
    folder = os.path.join(root or ROOT, "run_log")
    os.makedirs(folder, exist_ok=True)
    ts = ts or (meta or {}).get("ts") or time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, "%s_list.json" % ts)
    meta["run_log"] = path          # 先填再序列化，文件里才不会留空串
    return _atomic_write_text(
        path, json.dumps(meta, ensure_ascii=False, indent=2, default=str))


class RunFile:
    """一轮采集的增量落盘句柄：每页 append 一次，中途炸了前面几页仍在盘上。

    为什么不是采完再写：滚到第 3 页被风控、翻页超时、解析抛异常，
    都会把前 2 页已经采到的行一起丢掉，而且没有任何痕迹。
    改成 append + flush 后，异常时盘上那份就是"已采到的部分"。

    文件延迟到第一次 append 才创建，采到 0 条不会留下空文件。
    """

    def __init__(self, keyword, root=None):
        self.keyword = keyword
        self.folder = os.path.join(root or ROOT, "list_raw", keyword)
        self.path = ""
        self.rows = 0
        self._fh = None

    def append(self, rows):
        rows = list(rows or [])
        if not rows:
            return self.path
        if self._fh is None:
            os.makedirs(self.folder, exist_ok=True)
            self.path = os.path.join(
                self.folder, time.strftime("%Y%m%d_%H%M%S") + ".jsonl")
            self._fh = open(self.path, "a", encoding="utf-8")
        for row in rows:
            self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()          # 不 close 也已落盘，进程被杀/RPA 停跑都保得住
        self.rows += len(rows)
        return self.path

    def close(self):
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def save_rows(rows, keyword, root=None):
    """把一批商品写成 JSONL，返回文件路径。

    rows    : [{product_id, title, price, ...}, ...]
    keyword : 目录名（通常用配置里的 name 或 keyword）
    """
    folder = os.path.join(root or ROOT, "list_raw", keyword)
    os.makedirs(folder, exist_ok=True)

    path = os.path.join(folder, time.strftime("%Y%m%d_%H%M%S") + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows or []:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
