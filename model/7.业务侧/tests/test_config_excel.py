# -*- coding: utf-8 -*-
"""Excel 配置入口离线测试：不联网、不启浏览器。"""

import json
import os
import sys

import pytest
from openpyxl import Workbook

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _MODEL_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(_MODEL_DIR), "tool"))

import config_excel  # noqa: E402


def _xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "监控关键词"
    ws.append(config_excel.COLUMNS)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _row(**over):
    base = {
        "启用": "是", "名称": "枕头", "关键词": "护颈枕",
        "最低价": 20, "最高价": 1500, "包含词": "护颈,颈椎",
        "排除词": "汽车，车载", "最多翻页数": 3, "目标数量": 60,
        "排序": "销量", "备注": "示例",
    }
    base.update(over)
    return [base[c] for c in config_excel.COLUMNS]


def test_build_targets_valid():
    rows = [dict(zip(config_excel.COLUMNS,
                     _row()))]
    rows[0]["_row"] = 2
    targets, errors = config_excel.build_targets(rows)
    assert not errors
    assert targets[0]["keyword"] == "护颈枕"
    assert targets[0]["include"] == ["护颈", "颈椎"]
    assert targets[0]["exclude"] == ["汽车", "车载"]
    assert targets[0]["collect"] == {"max_pages": 3, "target_n": 60,
                                     "sort": "sale"}


def test_build_targets_invalid_price():
    rows = [dict(zip(config_excel.COLUMNS,
                     _row(最低价=2000, 最高价=100)))]
    rows[0]["_row"] = 2
    targets, errors = config_excel.build_targets(rows)
    assert not targets
    assert errors and "最低价大于最高价" in errors[0]["errors"]


def test_disabled_rows_skipped():
    rows = [dict(zip(config_excel.COLUMNS, _row(启用="否")))]
    rows[0]["_row"] = 2
    targets, errors = config_excel.build_targets(rows)
    assert not targets
    assert errors and "没有启用的监控关键词" in errors[0]["errors"]


def test_multi_enabled_rows_rejected():
    rows = [dict(zip(config_excel.COLUMNS, _row())),
            dict(zip(config_excel.COLUMNS, _row(名称="抱枕", 关键词="抱枕")))]
    rows[0]["_row"] = 2
    rows[1]["_row"] = 3
    targets, errors = config_excel.build_targets(rows)
    assert len(targets) == 2
    assert errors and "只支持单目标" in errors[0]["errors"][0]
    assert "枕头" in errors[0]["errors"][0] and "抱枕" in errors[0]["errors"][0]


def test_sync_multi_target_does_not_overwrite(tmp_path):
    xlsx = _xlsx(tmp_path / "监控关键词.xlsx",
                 [_row(), _row(名称="抱枕", 关键词="抱枕")])
    out = tmp_path / "targets.json"
    out.write_text('{"targets": [{"name": "旧目标"}]}', encoding="utf-8")
    before = out.read_text(encoding="utf-8")
    res = config_excel.sync(str(xlsx), str(out))
    assert not res["ok"]
    assert out.read_text(encoding="utf-8") == before


def test_sync_writes_json(tmp_path):
    xlsx = _xlsx(tmp_path / "监控关键词.xlsx", [_row()])
    out = tmp_path / "targets.json"
    res = config_excel.sync(str(xlsx), str(out))
    assert res["ok"] and res["count"] == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["targets"][0]["name"] == "枕头"
    assert data["defaults"]["collect"]["sort"] == "sale"


def test_sync_invalid_does_not_overwrite(tmp_path):
    xlsx = _xlsx(tmp_path / "监控关键词.xlsx", [_row(最低价=2000, 最高价=100)])
    out = tmp_path / "targets.json"
    out.write_text('{"targets": [{"name": "旧目标"}]}', encoding="utf-8")
    before = out.read_text(encoding="utf-8")
    res = config_excel.sync(str(xlsx), str(out))
    assert not res["ok"]
    assert out.read_text(encoding="utf-8") == before
