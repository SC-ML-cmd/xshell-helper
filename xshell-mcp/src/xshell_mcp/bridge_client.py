"""简化 IPC 客户端 — 与 Xshell 内 Bridge 通信"""

import json
import os
import time
from pathlib import Path

from .protocol import Request, Response


class BridgeClient:
    def __init__(self, ipc_dir: str, timeout: int = 30):
        self._ipc_dir = Path(ipc_dir)
        self._req_file = self._ipc_dir / ".request.json"
        self._resp_file = self._ipc_dir / ".response.json"
        self._timeout = timeout

    # ── IPC 核心 ──────────────────────────────────────

    def _send_request(self, req: Request) -> Response:
        self._ipc_dir.mkdir(parents=True, exist_ok=True)
        _remove_if_exists(self._resp_file)
        _write_json(self._req_file, req.__dict__)

        deadline = time.time() + self._timeout + 2
        while time.time() < deadline:
            data = _read_json(self._resp_file)
            if data:
                return Response.from_json(data)
            time.sleep(0.1)

        raise TimeoutError(f"Bridge 响应超时 ({self._timeout}s)")

    # ── 业务方法 ──────────────────────────────────────

    def check(self) -> bool:
        try:
            resp = self._send_request(Request(type="check"))
            return resp.success
        except Exception:
            return False

    def get_screen(self, lines: int = 50) -> Response:
        return self._send_request(Request(type="get_screen", lines=lines))

    def initialize(self):
        self._ipc_dir.mkdir(parents=True, exist_ok=True)


# ── 文件辅助 ─────────────────────────────────────────

def _write_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    try:
        os.replace(tmp, path)
    except OSError:
        pass


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _remove_if_exists(path):
    try:
        os.remove(str(path))
    except OSError:
        pass
