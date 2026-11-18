# -*- coding: utf-8 -*-
"""项目路径 SSOT：所有模块统一从这里取根目录，避免 P0-1 硬编码。

结构：
  <project>/model/tool/paths.py
  PROJECT = <project>
  RUNTIME = <project>/runtime
  CONFIG  = <project>/config
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
RUNTIME = os.path.join(PROJECT, "runtime")
CONFIG = os.path.join(PROJECT, "config")
PROFILE = os.path.join(RUNTIME, "profile")
STATE = os.path.join(RUNTIME, "state")
RUN_LOG = os.path.join(RUNTIME, "run_log")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def runtime_path(*parts):
    return os.path.join(RUNTIME, *parts)


def config_path(name):
    return os.path.join(CONFIG, name)


def state_path(name):
    return os.path.join(STATE, name)
