"""数据库连接：读 project-v2/config/database.json，不打印凭据。

约定：
  · 连接文件不入库（.gitignore 已排除 database.json）
  · 出错时只报 host/port/database，不把 password 带进日志
  · 允许 database 参数覆盖（测试库 / 多环境），默认取配置里的库名
"""

import json
import os

import pymysql

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
# _MODULE_DIR 已到 project-v2/model/4.数据入库，要退两层才是 project-v2/
# 影刀把 CodeFlow 复制到 xbot_robot 下执行，相对路径会指到应用目录；
# 因此与 1.列表页采集 同款：环境变量 > 相对仓库 > 本机绝对路径。
_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(_MODULE_DIR, "..", "..")),
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2",
]


def _first_project(candidates):
    for p in candidates:
        if p and os.path.isdir(os.path.join(p, "model")):
            return p
    return os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))


PROJECT_DIR = _first_project(_PROJECT_CANDIDATES)
DEFAULT_CONFIG = os.path.join(PROJECT_DIR, "config", "database.json")


def load_config(path=None):
    path = os.path.normpath(os.path.abspath(str(path or DEFAULT_CONFIG).strip().strip("\"'")))
    if not os.path.isfile(path):
        raise FileNotFoundError("找不到 database.json：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key in ("host", "port", "user", "password", "database"):
        if key not in cfg:
            raise KeyError("database.json 缺少字段：%s" % key)
    return cfg


def _connect(cfg, database):
    return pymysql.connect(
        host=cfg["host"], port=int(cfg["port"]), user=cfg["user"],
        password=cfg["password"], database=database,
        charset=cfg.get("charset", "utf8mb4"),
        autocommit=False, connect_timeout=8,
    )


def connect(config_path=None, database=None):
    """连业务库（默认 database.json 里的库名）。"""
    cfg = load_config(config_path)
    name = database or cfg["database"]
    try:
        return _connect(cfg, name)
    except pymysql.err.OperationalError as e:
        # 1009 = 库不存在；由 schema.ensure 负责建库
        if e.args and e.args[0] == 1049:
            raise
        raise


def connect_server(config_path=None):
    """不指定库，用于 CREATE DATABASE。"""
    cfg = load_config(config_path)
    return pymysql.connect(
        host=cfg["host"], port=int(cfg["port"]), user=cfg["user"],
        password=cfg["password"], charset=cfg.get("charset", "utf8mb4"),
        autocommit=True, connect_timeout=8,
    )


def describe(config_path=None, database=None):
    """用于日志的连接描述（绝不包含密码）。"""
    cfg = load_config(config_path)
    return "%s@%s:%s/%s" % (cfg["user"], cfg["host"], cfg["port"],
                            database or cfg["database"])


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
