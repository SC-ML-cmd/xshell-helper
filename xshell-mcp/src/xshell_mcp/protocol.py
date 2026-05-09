"""IPC 协议 — Request / Response 数据类"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Request:
    type: str = ""
    seq_id: str = ""
    cmd: str = ""
    marker: str = ""
    wait_for: str = ""
    timeout_ms: int = 30000
    lines: int = 50

    def __post_init__(self):
        if not self.seq_id:
            import time
            self.seq_id = str(int(time.time() * 1000000))

    def to_json(self) -> str:
        import json
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, s: str):
        import json
        return cls(**json.loads(s))


# Response 的已知字段白名单
_RESPONSE_FIELDS = {
    "success", "output", "timed_out", "start_row", "end_row",
    "screen_rows", "screen_cols", "error",
}


@dataclass
class Response:
    success: bool = True
    output: str = ""
    timed_out: bool = False
    start_row: int = 0
    end_row: int = 0
    screen_rows: int = 0
    screen_cols: int = 0
    error: str = ""

    @classmethod
    def from_json(cls, s: str):
        import json
        data = json.loads(s)
        filtered = {k: v for k, v in data.items() if k in _RESPONSE_FIELDS}
        return cls(**filtered)

    @staticmethod
    def error_response(msg: str):
        return Response(success=False, error=msg)
