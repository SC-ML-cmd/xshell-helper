"""
Xshell Bridge v8 — 超最小化，仅读屏幕
- time.sleep() 轮询（零 Session.Sleep，根除 COM native crash）
- 仅在请求到达时调用 Screen.Get()（COM 调用削减 1000 倍）
- 配合外部 SendInput 键盘发送命令使用
"""

import json
import os
import sys
import time as time_mod

# ============================================================
# 配置
# ============================================================
IPC_DIR = os.path.join(
    os.environ.get("TEMP", os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")),
    "xshell_mcp",
)
REQ_FILE = os.path.join(IPC_DIR, ".request.json")
RESP_FILE = os.path.join(IPC_DIR, ".response.json")
SCREEN_COLS = 200

if len(sys.argv) > 1:
    IPC_DIR = sys.argv[1]
    REQ_FILE = os.path.join(IPC_DIR, ".request.json")
    RESP_FILE = os.path.join(IPC_DIR, ".response.json")


# ============================================================
# 安全 COM 包装
# ============================================================

def _safe_current_row():
    try:
        return xsh.Screen.CurrentRow
    except Exception:
        return 0


def _safe_total_rows():
    try:
        return xsh.Screen.Rows
    except Exception:
        return 0


def _safe_read_screen(start_row, end_row):
    if start_row >= end_row:
        return ""
    try:
        return xsh.Screen.Get(start_row, 1, end_row, SCREEN_COLS)
    except Exception:
        return ""


# ============================================================
# 请求处理（仅 get_screen 和 check）
# ============================================================

def process_request(req):
    try:
        t = req.get("type", "")
        if t == "get_screen":
            return _handle_get_screen(req)
        elif t == "check":
            total = _safe_total_rows()
            return {
                "success": True, "output": "bridge v8 online", "timed_out": False,
                "start_row": 0, "end_row": 0,
                "screen_rows": total, "screen_cols": SCREEN_COLS,
            }
        else:
            return {"success": False, "error": "Unknown type: " + t, "output": ""}
    except Exception as e:
        return {
            "success": False, "output": "",
            "error": "process_request: {}".format(e),
            "timed_out": False, "start_row": 0, "end_row": 0,
            "screen_rows": 0, "screen_cols": SCREEN_COLS,
        }


def _handle_get_screen(req):
    lines = req.get("lines", 50)
    total_rows = _safe_total_rows()
    start_row = max(0, total_rows - lines)
    output = _safe_read_screen(start_row, total_rows)
    return {
        "success": True, "output": output, "timed_out": False,
        "start_row": start_row, "end_row": total_rows,
        "screen_rows": total_rows, "screen_cols": SCREEN_COLS,
    }


# ============================================================
# 主循环（零 Session.Sleep）
# ============================================================

def Main():
    if not os.path.isdir(IPC_DIR):
        os.makedirs(IPC_DIR, exist_ok=True)

    _write_resp({
        "success": True, "output": "bridge v8 started", "timed_out": False,
        "start_row": 0, "end_row": 0,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
    })

    last_mtime = 0

    while True:
        try:
            mtime = os.path.getmtime(REQ_FILE)
            if mtime > last_mtime:
                last_mtime = mtime
                req = _read_req()
                if req:
                    resp = process_request(req)
                    _write_resp(resp)
        except Exception:
            pass

        time_mod.sleep(0.5)


def _read_req():
    try:
        with open(REQ_FILE, "r") as f:
            return json.loads(f.read())
    except Exception:
        return None


def _write_resp(resp):
    try:
        tmp = RESP_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(resp))
        os.replace(tmp, RESP_FILE)
    except Exception:
        pass
