# -*- coding: utf-8 -*-
"""config_loader — 词单直读（影刀画布 009a 调 main，键名 config_path；纯 Python 亦可 import main）

返回整个 dict，不加工不校验：词单须五键齐全（keyword/min_price/max_price/include/exclude），
缺键或 JSON 语法错会在使用点/读取点自然炸出红字。精简版规则：出问题先查 keywords.json 本身。
"""
import json


def main(config_path):
    """读词单 JSON → 原样返回 dict（画布侧 glv['词单']['keyword'] 直接取用）。"""
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)
