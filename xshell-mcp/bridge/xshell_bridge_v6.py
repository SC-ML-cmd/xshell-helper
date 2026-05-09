"""
Xshell Bridge v6
- xsh.Screen.Send() 执行命令，安全稳定
- time.sleep 替代 xsh.Session.Sleep，防止空闲 COM native crash
- 缓存 shell 分隔符检测结果
- 全面 Exception 捕获
- 心跳文件
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
HEARTBEAT_FILE = os.path.join(IPC_DIR, ".heartbeat.json")
SCREEN_COLS = 200

if len(sys.argv) > 1:
    IPC_DIR = sys.argv[1]
    REQ_FILE = os.path.join(IPC_DIR, ".request.json")
    RESP_FILE = os.path.join(IPC_DIR, ".response.json")
    HEARTBEAT_FILE = os.path.join(IPC_DIR, ".heartbeat.json")

# ============================================================
# Shell 检测（缓存结果，只检测一次）
# ============================================================

_SEPARATOR = None


def _detect_separator():
    global _SEPARATOR
    if _SEPARATOR is not None:
        return _SEPARATOR
    try:
        end = _safe_current_row()
        recent = _safe_read_screen(max(0, end - 5), end)
        last_line = recent.split("\n")[-1] if recent else ""
        if ">" in last_line[-3:] and ":\\" not in last_line[-60:]:
            _SEPARATOR = ";" if "PS " in last_line else "&"
        else:
            _SEPARATOR = ";"
    except Exception:
        _SEPARATOR = ";"
    return _SEPARATOR


# ============================================================
# 请求处理
# ============================================================

def process_request(req):
    try:
        t = req.get("type", "")
        if t == "exec":
            return _handle_exec(req)
        elif t == "send_raw":
            return _handle_send_raw(req)
        elif t == "get_screen":
            return _handle_get_screen(req)
        elif t == "interrupt":
            return _handle_interrupt()
        elif t == "check":
            return _handle_check()
        else:
            return {"success": False, "error": "Unknown type: " + t, "output": ""}
    except Exception as e:
        return {
            "success": False, "output": "",
            "error": "process_request: {}".format(e),
            "timed_out": False, "start_row": 0, "end_row": 0,
            "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
        }


def _handle_exec(req):
    start_row = _safe_current_row()
    cmd = req.get("cmd", "")
    marker = req.get("marker", "")
    timeout_ms = req.get("timeout_ms", 30000)

    sep = _detect_separator()
    full_cmd = cmd + " " + sep + " echo " + marker
    xsh.Screen.Send(full_cmd + "\r")

    timed_out = True
    elapsed = 0
    while elapsed < timeout_ms:
        time_mod.sleep(0.2)
        elapsed += 200
        recent = _safe_read_screen(max(0, _safe_current_row() - 8), _safe_current_row())
        if marker in recent:
            timed_out = False
            break

    end_row = _safe_current_row()
    output = _safe_read_screen(start_row, end_row)

    return {
        "success": not timed_out, "output": output, "timed_out": timed_out,
        "start_row": start_row, "end_row": end_row,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
    }


def _handle_send_raw(req):
    start_row = _safe_current_row()
    text = req.get("cmd", "")
    wait_for = req.get("wait_for", "")
    timeout_ms = req.get("timeout_ms", 30000)

    xsh.Screen.Send(text)

    timed_out = True
    if wait_for:
        elapsed = 0
        while elapsed < timeout_ms:
            time_mod.sleep(0.2)
            elapsed += 200
            recent = _safe_read_screen(max(0, _safe_current_row() - 8), _safe_current_row())
            if wait_for in recent:
                timed_out = False
                break
    else:
        timed_out = False

    end_row = _safe_current_row()
    output = _safe_read_screen(start_row, end_row)

    return {
        "success": not timed_out, "output": output, "timed_out": timed_out,
        "start_row": start_row, "end_row": end_row,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
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


def _handle_interrupt():
    xsh.Screen.Send("\x03")
    return {
        "success": True, "output": "", "timed_out": False,
        "start_row": 0, "end_row": 0,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
    }


def _handle_check():
    return {
        "success": True, "output": "bridge v6 online",
        "timed_out": False, "start_row": 0, "end_row": 0,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
        "current_row": _safe_current_row(), "connected": _safe_is_connected(),
    }


# ============================================================
# 终端辅助（安全包装，COM 失败不崩溃）
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


def _safe_is_connected():
    try:
        return xsh.Session.Connected
    except Exception:
        return False


def _safe_read_screen(start_row, end_row):
    if start_row >= end_row:
        return ""
    try:
        return xsh.Screen.Get(start_row, 1, end_row, SCREEN_COLS)
    except Exception:
        return ""


# ============================================================
# 心跳
# ============================================================

def _write_heartbeat():
    try:
        data = json.dumps({
            "ts": time_mod.time(),
            "current_row": _safe_current_row(),
            "total_rows": _safe_total_rows(),
        })
        tmp = HEARTBEAT_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, HEARTBEAT_FILE)
    except Exception:
        pass


# ============================================================
# 主循环
# ============================================================

def Main():
    try:
        xsh.Screen.Synchronous = True
    except Exception:
        pass

    if not os.path.isdir(IPC_DIR):
        os.makedirs(IPC_DIR, exist_ok=True)

    _write_resp({
        "success": True, "output": "bridge v6 started", "timed_out": False,
        "start_row": 0, "end_row": 0, "screen_rows": _safe_total_rows(),
        "screen_cols": SCREEN_COLS, "current_row": _safe_current_row(),
    })

    last_mtime = 0
    last_heartbeat = 0

    while True:
        try:
            mtime = os.path.getmtime(REQ_FILE)
            if mtime > last_mtime:
                last_mtime = mtime
                req = _read_req()
                if req:
                    resp = process_request(req)
                    _write_resp(resp)

            now = time_mod.time()
            if now - last_heartbeat >= 2.0:
                _write_heartbeat()
                last_heartbeat = now

        except Exception:
            pass

        time_mod.sleep(0.2)


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
