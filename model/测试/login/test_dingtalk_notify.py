# -*- coding: utf-8 -*-
"""节点 0 · 离线回归：钉钉通知（加签 / 关键词 / 未配置）。

不联网：mock urllib.request.urlopen，只验证 URL 与 payload。
运行：python 测试/login/test_dingtalk_notify.py
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

TOOLBOX_DIR = Path(__file__).resolve().parents[2] / "tool"
sys.path.insert(0, str(TOOLBOX_DIR))

import dingtalk_notify as dn  # noqa: E402


class FakeResp:
    status = 200

    def read(self):
        return b'{"errcode":0}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main() -> int:
    passed = 0
    total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += 1 if cond else 0
        print(("PASS" if cond else "FAIL"), name)

    signed = dn._signed_url("https://oapi.dingtalk.com/robot/send?access_token=a",
                            "SECtest")
    check("加签 URL 带 timestamp/sign",
          "timestamp=" in signed and "sign=" in signed)
    check("无 secret 不改 URL",
          dn._signed_url("https://example.invalid", "") == "https://example.invalid")

    with patch.object(dn, "_cred", return_value=("", "", "")):
        check("未配置 -> skipped", dn.send_text("x").get("status") == "skipped")

    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    with patch.object(dn, "_cred",
                      return_value=("https://example.invalid?access_token=a",
                                    "SECtest", "小天才Z6pro")):
        with patch.object(dn.urllib.request, "urlopen", fake_urlopen):
            res = dn.send_text("正文", title="标题")

    check("发送成功", res.get("status") == "ok")
    check("关键词拼进正文",
          captured["payload"]["markdown"]["text"].startswith("小天才Z6pro"))
    check("payload 是 markdown",
          captured["payload"].get("msgtype") == "markdown")
    check("加签拼进请求 URL", "timestamp=" in captured["url"])

    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
