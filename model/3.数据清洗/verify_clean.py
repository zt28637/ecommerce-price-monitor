# -*- coding: utf-8 -*-
"""N3.7 幂等与对账：run_meta / 计数 / 产物哈希。"""

import datetime
import hashlib
import os

import export


def file_hashes(paths):
    out = {}
    for p in paths or []:
        try:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            out[os.path.basename(p)] = h.hexdigest()
        except OSError:
            out[os.path.basename(p)] = ""
    return out


def build_meta(date, out_dir, args, counts, list_stats, detail_stats,
               report_path, output_files):
    """组装 run_meta；对账口径 = counts + 文件列表 + 哈希。"""
    outputs = [report_path] + list(output_files or [])
    return {
        "date": date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "out_dir": out_dir,
        "args": {k: v for k, v in (args or {}).items() if k != "cfg"},
        "counts": counts,
        "files": {"list": (list_stats or {}).get("files", []),
                  "detail": (detail_stats or {}).get("files", [])},
        "outputs": outputs,
        "hashes": file_hashes([p for p in outputs if p.endswith(".jsonl")]),
    }


def write_meta(out_dir, meta):
    path = os.path.join(out_dir, "run_meta.json")
    export.write_json(path, meta)
    return path


def main(args=None):
    return {"ok": True}
