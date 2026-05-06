"""
Xshell Bridge v5
- Windows API 键盘模拟替代 xsh.Screen.Send()，命令在 Xshell 窗口中可见
- 轮询检测 marker，不依赖 WaitForStrings API
- 缓存 shell 类型检测结果
- 全面异常捕获，防止 COM 错误导致脚本崩溃
- 心跳文件机制（纯文件 I/O，零 COM）
- check 请求零 COM 调用
- 自适应轮询间隔（500ms/1000ms）
- 屏幕缓冲自动清理
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
# Windows API — 键盘模拟（ctypes 可选，不可用时回退到 xsh.Screen.Send）
# ============================================================

_HAS_SENDINPUT = False

try:
    import ctypes
    from ctypes import wintypes

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008

    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", INPUT_UNION),
        ]

    def _send_input(inp):
        user32 = ctypes.windll.user32
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def _key_event(vk, up=False):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        if up:
            inp.union.ki.dwFlags = KEYEVENTF_KEYUP
        _send_input(inp)

    def _char_event(ch):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wScan = ord(ch)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE
        _send_input(inp)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _send_input(inp)

    def _find_xshell_terminal_window():
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        current_pid = kernel32.GetCurrentProcessId()
        result = []

        def _enum_child(hwnd, _):
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            cn = class_name.value
            if cn and ("Afx" in cn or "View" in cn or "Edit" in cn or "Term" in cn or "Console" in cn):
                result.append(hwnd)
            return True

        def _enum_top(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == current_pid:
                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum_child), 0)
                return not result
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(_enum_top), 0)
        return result[0] if result else None

    def _ensure_foreground_and_focus(hwnd):
        user32 = ctypes.windll.user32
        if not hwnd:
            return False
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        user32.SetForegroundWindow(hwnd)
        xsh.Session.Sleep(50)
        return user32.GetForegroundWindow() == hwnd

    def _send_input_text(text, hwnd):
        """通过 Windows SendInput 向 Xshell 发送文本（在窗口中可见）"""
        _ensure_foreground_and_focus(hwnd)
        for ch in text:
            if ch == '\r' or ch == '\n':
                _key_event(VK_RETURN)
                _key_event(VK_RETURN, up=True)
            elif ch == '\x03':
                _key_event(VK_CONTROL)
                _char_event('c')
                _key_event(VK_CONTROL, up=True)
            elif ch == '\t':
                _key_event(0x09)
                _key_event(0x09, up=True)
            else:
                _char_event(ch)

    # 缓存 Xshell 终端窗口句柄
    _TERMINAL_HWND = None

    def _get_terminal_hwnd():
        global _TERMINAL_HWND
        if _TERMINAL_HWND is None:
            _TERMINAL_HWND = _find_xshell_terminal_window()
        return _TERMINAL_HWND

    _HAS_SENDINPUT = True

except ImportError:
    pass


def _send_text(text, _hwnd=None):
    """发送文本到 Xshell 终端。优先使用 SendInput（窗口可见），不可用时回退到 xsh.Screen.Send。"""
    if _HAS_SENDINPUT:
        hwnd = _hwnd if _hwnd else _get_terminal_hwnd()
        if hwnd:
            try:
                _send_input_text(text, hwnd)
                return
            except Exception:
                pass
    # 回退
    xsh.Screen.Send(text)


def _send_text_fallback(text):
    """直接使用 xsh.Screen.Send"""
    xsh.Screen.Send(text)


# ============================================================
# 屏幕缓冲清理（避免 COM Get 读取超大数据块）
# ============================================================

_SCREEN_LAST_CLEAR = 0


def _maybe_clear_screen():
    global _SCREEN_LAST_CLEAR
    try:
        total_rows = _safe_total_rows()
        now = time_mod.time()
        if total_rows > 200 and (now - _SCREEN_LAST_CLEAR) > 1800:
            _send_text("clear\r")
            xsh.Session.Sleep(400)
            _SCREEN_LAST_CLEAR = now
    except Exception:
        pass


# ============================================================
# Shell 检测（带缓存）
# ============================================================

_SEPARATOR_CACHE = None


def _detect_separator():
    """检测当前 shell 类型，返回正确的命令分隔符。结果缓存，只检测一次。"""
    global _SEPARATOR_CACHE
    if _SEPARATOR_CACHE is not None:
        return _SEPARATOR_CACHE

    try:
        end = _current_row()
        start = max(0, end - 5)
        recent = _read_screen(start, end)
        last_line = recent.split("\n")[-1] if recent else ""

        if ">" in last_line[-3:] and ":\\" not in last_line[-60:]:
            if "PS " in last_line:
                _SEPARATOR_CACHE = ";"
            else:
                _SEPARATOR_CACHE = "&"
        else:
            _SEPARATOR_CACHE = ";"
    except Exception:
        _SEPARATOR_CACHE = ";"

    return _SEPARATOR_CACHE


# ============================================================
# 请求处理
# ============================================================

def process_request(req):
    """处理请求，顶层 try/except 确保单个请求失败不会导致脚本退出"""
    try:
        return _process_request_impl(req)
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": "process_request exception: {}".format(e),
            "timed_out": False,
            "start_row": 0,
            "end_row": 0,
            "screen_rows": _safe_total_rows(),
            "screen_cols": SCREEN_COLS,
        }


def _process_request_impl(req):
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


def _handle_exec(req):
    start_row = _safe_current_row()
    cmd = req.get("cmd", "")
    marker = req.get("marker", "")
    timeout_ms = req.get("timeout_ms", 30000)

    sep = _detect_separator()
    full_cmd = cmd + " " + sep + " echo " + marker

    _send_text(full_cmd + "\r")

    # 轮询等待 marker（自适应间隔 + COM 故障退避）
    timed_out = True
    elapsed = 0
    com_failures = 0
    while elapsed < timeout_ms:
        wait = 500 if elapsed < 5000 else 1000
        xsh.Session.Sleep(wait)
        elapsed += wait
        end_row = _safe_current_row()
        chk_start = max(0, end_row - 8)
        recent = _safe_read_screen(chk_start, end_row)
        if marker in recent:
            timed_out = False
            break
        # COM 连续失败 → 延长等待，避免在异常状态下频繁重试
        if end_row == 0 and not recent:
            com_failures += 1
            if com_failures > 10:
                xsh.Session.Sleep(2000)
                elapsed += 2000
        else:
            com_failures = 0

    end_row = _safe_current_row()
    output = _safe_read_screen(start_row, end_row)

    _maybe_clear_screen()

    return {
        "success": not timed_out,
        "output": output,
        "timed_out": timed_out,
        "start_row": start_row,
        "end_row": end_row,
        "screen_rows": _safe_total_rows(),
        "screen_cols": SCREEN_COLS,
    }


def _handle_send_raw(req):
    start_row = _safe_current_row()
    text = req.get("cmd", "")
    wait_for = req.get("wait_for", "")
    timeout_ms = req.get("timeout_ms", 30000)

    _send_text(text)

    timed_out = True
    if wait_for:
        elapsed = 0
        com_failures = 0
        while elapsed < timeout_ms:
            wait = 500 if elapsed < 5000 else 1000
            xsh.Session.Sleep(wait)
            elapsed += wait
            end_row = _safe_current_row()
            chk_start = max(0, end_row - 8)
            recent = _safe_read_screen(chk_start, end_row)
            if wait_for in recent:
                timed_out = False
                break
            if end_row == 0 and not recent:
                com_failures += 1
                if com_failures > 10:
                    xsh.Session.Sleep(2000)
                    elapsed += 2000
            else:
                com_failures = 0
    else:
        timed_out = False

    end_row = _safe_current_row()
    output = _safe_read_screen(start_row, end_row)

    _maybe_clear_screen()

    return {
        "success": not timed_out,
        "output": output,
        "timed_out": timed_out,
        "start_row": start_row,
        "end_row": end_row,
        "screen_rows": _safe_total_rows(),
        "screen_cols": SCREEN_COLS,
    }


def _handle_get_screen(req):
    lines = req.get("lines", 50)
    total_rows = _safe_total_rows()
    start_row = max(0, total_rows - lines)
    output = _safe_read_screen(start_row, total_rows)

    return {
        "success": True,
        "output": output,
        "timed_out": False,
        "start_row": start_row,
        "end_row": total_rows,
        "screen_rows": total_rows,
        "screen_cols": SCREEN_COLS,
    }


def _handle_interrupt():
    _send_text("\x03")
    return {
        "success": True, "output": "", "timed_out": False,
        "start_row": 0, "end_row": 0,
        "screen_rows": _safe_total_rows(), "screen_cols": SCREEN_COLS,
    }


def _handle_check():
    # 完全不调用 COM，避免触发 Xshell COM 服务崩溃
    return {
        "success": True, "output": "bridge v5 online",
        "timed_out": False, "start_row": 0, "end_row": 0,
        "screen_rows": 0, "screen_cols": SCREEN_COLS,
        "current_row": 0, "connected": True,
    }


# ============================================================
# 终端辅助（安全包装，COM 调用失败不崩溃）
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


# 别名，保持与 v3 兼容
_current_row = _safe_current_row
_total_rows = _safe_total_rows
_is_connected = _safe_is_connected
_read_screen = _safe_read_screen


# ============================================================
# 心跳（纯文件 I/O，零 COM）
# ============================================================

def _write_heartbeat():
    try:
        data = json.dumps({"ts": time_mod.time()})
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
        "success": True, "output": "bridge v5 started", "timed_out": False,
        "start_row": 0, "end_row": 0, "screen_rows": _safe_total_rows(),
        "screen_cols": SCREEN_COLS, "current_row": _safe_current_row(),
    })

    last_mtime = 0
    last_heartbeat = 0
    hb_interval = 2.0

    while True:
        try:
            mtime = os.path.getmtime(REQ_FILE)
            if mtime > last_mtime:
                last_mtime = mtime
                req = _read_req()
                if req:
                    resp = process_request(req)
                    _write_resp(resp)

            # 心跳
            now = time_mod.time()
            if now - last_heartbeat >= hb_interval:
                _write_heartbeat()
                last_heartbeat = now

        except Exception:
            # 捕获所有异常，防止 COM 错误等导致脚本退出
            pass

        try:
            xsh.Session.Sleep(500)
        except Exception:
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


# ============================================================
# 入口
# Xshell 手动"运行脚本"时会自动查找并调用 Main()
# 命令行 -script 参数启动时，需要显式调用（先写启动标记证明脚本被执行）
# ============================================================
_STARTUP_FLAG = os.path.join(IPC_DIR, ".bridge_startup.txt")
try:
    with open(_STARTUP_FLAG, "w") as f:
        f.write("bridge_v5_started: {}".format(time_mod.time()))
except Exception:
    pass

# 显式调用 Main()，兼容 -script 命令行启动
# 如果 Xshell 也自动调了 Main() 会导致双重运行——但 Main() 中的 while True
# 循环会阻止第二次调用，所以是安全的
try:
    Main()
except Exception as startup_err:
    try:
        with open(_STARTUP_FLAG, "w") as f:
            f.write("bridge_v5_failed: {}".format(startup_err))
    except Exception:
        pass
