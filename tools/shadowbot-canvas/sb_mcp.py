"""影刀编辑器 studio-mcp 客户端（本地真源读取）

影刀编辑器运行时在本机开一个 Streamable-HTTP MCP 服务（EmbedIO），
Copilot 就是用它读写流程画布。这里复用同一接口，把"真源"指令块
拉成纯文本清单——不解密、不逆向，走的官方本地接口。

用法:
    python sb_mcp.py                      # 列出编辑器当前应用的全部流程
    python sb_mcp.py blocks <flow名>       # 打印某流程的指令块原文(json)
"""

import json
import os
import re
import urllib.request

_LOG_DIR = r"C:\Users\Admin\AppData\Local\ShadowBot\log"
_MCP_PATH = "/api/v1/mcp"


def _mcp_alive(port: int) -> bool:
    """对候选端口做一次 MCP initialize 握手，通了才算。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1.0"},
        },
    }
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{_MCP_PATH}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return b"serverInfo" in resp.read()
    except Exception:
        return False


_PORT_CACHE = os.path.join(os.environ.get("TEMP", "."), "sb_mcp_port.txt")


def discover_port() -> int:
    """从影刀日志里收集候选端口并逐一握手，找到编辑器当前的 MCP 端口。

    编辑器当天日志可能只记启动信息（不含端口），且端口会跨天沿用；
    因此扫描最近 20 份日志，并用上次成功的端口缓存兜底。
    """
    import glob
    import os

    logs = sorted(glob.glob(os.path.join(_LOG_DIR, "*.log")), key=os.path.getmtime, reverse=True)
    candidates: list[int] = []

    def add(port: int) -> None:
        if port not in candidates:
            candidates.append(port)

    # 上次成功的端口优先（编辑器重启后端口通常会变，握手失败会自动跳过）
    try:
        with open(_PORT_CACHE, encoding="utf-8") as f:
            add(int(f.read().strip()))
    except (OSError, ValueError):
        pass

    for lg in logs[:20]:
        try:
            with open(lg, "rb") as f:
                data = f.read()
        except OSError:
            continue
        for p in reversed(re.findall(rb"127\.0\.0\.1:(\d{4,5})", data)):
            add(int(p))
    for port in candidates:
        if _mcp_alive(port):
            try:
                with open(_PORT_CACHE, "w", encoding="utf-8") as f:
                    f.write(str(port))
            except OSError:
                pass
            return port
    raise RuntimeError("未发现影刀编辑器 MCP 端口——请确认编辑器已启动并停在应用页")


def call(tool: str, arguments: dict | None = None, port: int | None = None, timeout: int = 60):
    """调用一个 studio-mcp 工具，返回解析后的 JSON 内容。"""
    port = port or discover_port()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{_MCP_PATH}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    # 兼容 SSE 帧：data: {...}
    for line in body.splitlines():
        if line.startswith("data:"):
            body = line[5:].strip()
            break
    rpc = json.loads(body)
    if "error" in rpc:
        raise RuntimeError(f"{tool}: {rpc['error']}")
    content = rpc["result"]["content"][0]["text"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    port = discover_port()
    print(f"[mcp port] {port}")
    if len(sys.argv) >= 2 and sys.argv[1] == "blocks":
        print(json.dumps(call("flow.blocks.list", {"flow": sys.argv[2]}, port), ensure_ascii=False, indent=1)[:6000])
    else:
        print(json.dumps(call("app.list_flows", {}, port), ensure_ascii=False, indent=1))
