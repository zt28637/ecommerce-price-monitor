# -*- coding: utf-8 -*-
"""random_sleep — 亚秒级随机等待（影刀画布 programing.sleep 实测不支持小数秒 · 2026-10-08）

画布「调用模块」用法：arguments.min_seconds / max_seconds → 返回值存变量（实际睡秒，可打日志观测）。
边界纪律：纯睡眠、零决策——骰子/IF/节奏全在画布；本模块只是把等待粒度补到亚秒，不是逻辑层。
"""
import random
import time


def main(min_seconds, max_seconds):
    """在 [min, max] 秒内均匀随机休眠，返回实际睡秒数（float）。"""
    lo = max(float(min_seconds), 0.0)
    hi = max(float(max_seconds), 0.0)
    if lo > hi:
        lo, hi = hi, lo
    t = random.uniform(lo, hi)
    time.sleep(t)
    return t
