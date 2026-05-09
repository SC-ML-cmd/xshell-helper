"""
Xshell 外部控制器 — SendInput 键盘模拟 + 剪贴板读取（零 COM 调用）

从进程外控制 Xshell GUI，不依赖任何 Xshell COM API。
Windows API 结构体（INPUT/KEYBDINPUT/INPUT_UNION/SendInput）从 bridge v4 复用。
"""

import ctypes
from ctypes import wintypes
import time
import logging

logger = logging.getLogger("xshell_mcp")

# ============================================================
# Windows API 常量
# ============================================================

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_A = 0x41
VK_C = 0x43
VK_END = 0x23
VK_PRIOR = 0x21  # PageUp
VK_NEXT = 0x22   # PageDown

CF_TEXT = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

TH32CS_SNAPPROCESS = 0x00000002

SW_RESTORE = 9
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001


# ============================================================
# Windows API 类型定义 — 从 bridge v4 直接复用
# ============================================================

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


# ============================================================
# DLL 引用 + 64 位安全签名
# ============================================================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# SendInput
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

# 剪贴板
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

# 窗口查找
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int


# ============================================================
# 窗口查找
# ============================================================

def _find_process_ids(process_name: str) -> list:
    """通过 tasklist 命令获取进程 PID（避免 64 位 PROCESSENTRY32 对齐问题）"""
    import subprocess
    try:
        result = subprocess.run(
            ["cmd", "/c", "tasklist", "/FI", f"IMAGENAME eq {process_name}",
             "/FO", "CSV", "/NH"],
            capture_output=True, timeout=10,
        )
        output = result.stdout.decode("gbk", errors="ignore")
        pids = []
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            # 格式: "XshellCore.exe","61432","Console","1","71,260 K"
            parts = line.strip('"').split('","')
            if len(parts) >= 2:
                try:
                    pids.append(int(parts[1].strip('"')))
                except ValueError:
                    continue
        return pids
    except Exception:
        return []


def find_xshell_window():
    """查找 Xshell 顶层窗口句柄"""
    pids = _find_process_ids("XshellCore.exe")
    if not pids:
        return None

    target_pids = set(pids)
    found = []

    def _enum_proc(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in target_pids:
            found.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)

    for hwnd in found:
        if user32.IsWindowVisible(hwnd):
            return hwnd
    return found[0] if found else None


def find_terminal_child(parent_hwnd):
    """在 Xshell 顶层窗口下找到终端子窗口"""
    result = []

    def _enum_child(hwnd, _):
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        cn = class_name.value
        if cn and ("Afx" in cn or "View" in cn or "Edit" in cn or "Term" in cn or "Console" in cn):
            result.append(hwnd)
            logger.info("找到终端子窗口，类名: %s, hwnd: %s", cn, hwnd)
            return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(_enum_child), 0)
    return result[0] if result else parent_hwnd  # 回退：直接用顶层窗口


# ============================================================
# 前台切换
# ============================================================

def ensure_foreground(hwnd):
    """确保目标窗口在前台"""
    try:
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True

        # 策略1: 标准 SetForegroundWindow
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        if user32.GetForegroundWindow() == hwnd:
            return True

        # 策略2: 强制恢复窗口并置顶
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


# ============================================================
# SendInput 键盘模拟 — 从 bridge v4 复用
# ============================================================

def _send_one_input(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _key_down_up(vk):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    _send_one_input(inp)
    time.sleep(0.001)
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP
    _send_one_input(inp)


def _unicode_char(ch):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wScan = ord(ch)
    inp.union.ki.dwFlags = KEYEVENTF_UNICODE
    _send_one_input(inp)
    time.sleep(0.001)
    inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    _send_one_input(inp)


def _ctrl_key(vk):
    """发送 Ctrl+Key 组合键"""
    ctrl_inp = INPUT()
    ctrl_inp.type = INPUT_KEYBOARD
    ctrl_inp.union.ki.wVk = VK_CONTROL
    _send_one_input(ctrl_inp)
    time.sleep(0.02)
    _key_down_up(vk)
    time.sleep(0.02)
    ctrl_inp.union.ki.dwFlags = KEYEVENTF_KEYUP
    _send_one_input(ctrl_inp)

def _ctrl_insert():
    """Ctrl+Insert — Xshell 的复制快捷键（Ctrl+C 在终端中是 SIGINT）"""
    ctrl_inp = INPUT()
    ctrl_inp.type = INPUT_KEYBOARD
    ctrl_inp.union.ki.wVk = VK_CONTROL
    _send_one_input(ctrl_inp)
    time.sleep(0.02)
    _key_down_up(0x2D)  # VK_INSERT
    time.sleep(0.02)
    ctrl_inp.union.ki.dwFlags = KEYEVENTF_KEYUP
    _send_one_input(ctrl_inp)


def send_text(text):
    """通过 SendInput 逐字符发送文本到当前前台窗口。

    使用虚拟键码（wVk）而非 Unicode（KEYEVENTF_UNICODE），
    因为 Xshell 终端只处理虚拟键码键盘事件。"""
    for ch in text:
        if ch == '\r' or ch == '\n':
            _key_down_up(VK_RETURN)
        elif ch == '\t':
            _key_down_up(0x09)
        elif ch == '\x03':
            _ctrl_key(VK_C)
        else:
            _send_char(ch)
    time.sleep(0.01)


def _send_char(ch):
    """用虚拟键码发送单个字符（支持 Shift 状态）"""
    vk, shift = _char_to_vk(ch)
    if vk is None:
        # 无法映射的字符，回退到 Unicode 方式
        _unicode_char(ch)
        return

    if shift:
        shift_inp = INPUT()
        shift_inp.type = INPUT_KEYBOARD
        shift_inp.union.ki.wVk = 0x10  # VK_SHIFT
        _send_one_input(shift_inp)
        time.sleep(0.002)

    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    _send_one_input(inp)
    time.sleep(0.002)
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP
    _send_one_input(inp)

    if shift:
        shift_inp.union.ki.dwFlags = KEYEVENTF_KEYUP
        _send_one_input(shift_inp)
    time.sleep(0.002)


def _char_to_vk(ch):
    """将字符映射为 (虚拟键码, 是否需要Shift)"""
    # 数字 0-9: VK 0x30-0x39
    if '0' <= ch <= '9':
        return ord(ch), False
    # 大写字母 A-Z: VK 0x41-0x5A
    if 'A' <= ch <= 'Z':
        return ord(ch), False
    # 小写字母 a-z: VK 0x41-0x5A + Shift
    if 'a' <= ch <= 'z':
        return ord(ch.upper()), True

    # 常见符号映射
    _SYMBOL_MAP = {
        ' ': (0x20, False),     # VK_SPACE
        '-': (0xBD, False),     # VK_OEM_MINUS
        '_': (0xBD, True),      # VK_OEM_MINUS + Shift
        '=': (0xBB, False),     # VK_OEM_PLUS
        '+': (0xBB, True),
        '[': (0xDB, False),
        '{': (0xDB, True),
        ']': (0xDD, False),
        '}': (0xDD, True),
        ';': (0xBA, False),
        ':': (0xBA, True),
        "'": (0xDE, False),
        '"': (0xDE, True),
        ',': (0xBC, False),
        '<': (0xBC, True),
        '.': (0xBE, False),
        '>': (0xBE, True),
        '/': (0xBF, False),
        '?': (0xBF, True),
        '\\': (0xDC, False),
        '|': (0xDC, True),
        '`': (0xC0, False),
        '~': (0xC0, True),
        '!': (0x31, True),     # 1 + Shift
        '@': (0x32, True),     # 2 + Shift
        '#': (0x33, True),     # 3 + Shift
        '$': (0x34, True),     # 4 + Shift
        '%': (0x35, True),     # 5 + Shift
        '^': (0x36, True),     # 6 + Shift
        '&': (0x37, True),     # 7 + Shift
        '*': (0x38, True),     # 8 + Shift
        '(': (0x39, True),     # 9 + Shift
        ')': (0x30, True),     # 0 + Shift
    }
    return _SYMBOL_MAP.get(ch, (None, False))


# ============================================================
# 剪贴板操作
# ============================================================

class XshellClipboard:
    """剪贴板保存 → 读取 → 恢复 上下文"""

    def __init__(self):
        self._saved_text = None

    def save(self):
        """保存当前剪贴板文本"""
        self._saved_text = ""
        for attempt in range(3):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.1)
        else:
            return

        try:
            # 优先 CF_UNICODETEXT
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if h_data:
                ptr = kernel32.GlobalLock(h_data)
                if ptr:
                    try:
                        self._saved_text = ctypes.wstring_at(ptr)
                    finally:
                        kernel32.GlobalUnlock(h_data)
            else:
                h_data = user32.GetClipboardData(CF_TEXT)
                if h_data:
                    ptr = kernel32.GlobalLock(h_data)
                    if ptr:
                        try:
                            raw = ctypes.c_char_p(ptr).value
                            self._saved_text = raw.decode("utf-8", errors="replace") if raw else ""
                        finally:
                            kernel32.GlobalUnlock(h_data)
        except Exception:
            pass
        finally:
            user32.CloseClipboard()

    def read(self) -> str:
        """读当前剪贴板文本"""
        for attempt in range(3):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.1)
        else:
            return ""

        try:
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if h_data:
                ptr = kernel32.GlobalLock(h_data)
                if ptr:
                    try:
                        return ctypes.wstring_at(ptr)
                    finally:
                        kernel32.GlobalUnlock(h_data)

            h_data = user32.GetClipboardData(CF_TEXT)
            if h_data:
                ptr = kernel32.GlobalLock(h_data)
                if ptr:
                    try:
                        raw = ctypes.c_char_p(ptr).value
                        return raw.decode("utf-8", errors="replace") if raw else ""
                    finally:
                        kernel32.GlobalUnlock(h_data)
            return ""
        except Exception:
            return ""
        finally:
            user32.CloseClipboard()

    def restore(self):
        """恢复之前保存的剪贴板内容"""
        if not self._saved_text:
            return

        for attempt in range(3):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.1)
        else:
            return

        try:
            user32.EmptyClipboard()
            text_utf16 = self._saved_text + "\0"
            size = len(text_utf16) * 2
            h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if h_global:
                ptr = kernel32.GlobalLock(h_global)
                if ptr:
                    try:
                        ctypes.memmove(ptr, text_utf16.encode("utf-16-le"), size)
                    finally:
                        kernel32.GlobalUnlock(h_global)
                user32.SetClipboardData(CF_UNICODETEXT, h_global)
        except Exception:
            pass
        finally:
            user32.CloseClipboard()


# ============================================================
# 终端读取（通过剪贴板）
# ============================================================

def copy_terminal_all(hwnd) -> str:
    """Ctrl+A 全选 → Ctrl+Insert 复制 → 读剪贴板 → 恢复

    Xshell 中 Ctrl+A 是全选快捷键，Ctrl+Insert 是复制快捷键。
    不能用 Ctrl+C，因为终端中 Ctrl+C 是 SIGINT 而非复制。"""
    ensure_foreground(hwnd)
    time.sleep(0.05)

    clip = XshellClipboard()
    clip.save()

    try:
        _ctrl_key(VK_A)       # Ctrl+A 全选
        time.sleep(0.1)
        _ctrl_insert()        # Ctrl+Insert 复制
        time.sleep(0.08)
        return clip.read()
    finally:
        clip.restore()


def copy_terminal_tail(hwnd, n_lines=50) -> str:
    """读取终端最后 N 行（全选复制后用 Python 截断）"""
    full = copy_terminal_all(hwnd)
    if not full:
        return ""
    lines = full.split("\n")
    return "\n".join(lines[-n_lines:]) if len(lines) > n_lines else full


# ============================================================
# Shell 分隔符检测（纯文本分析，无 COM）
# ============================================================

def detect_separator(tail_text: str) -> str:
    """从终端文本检测 shell 类型，返回命令分隔符"""
    lines = tail_text.strip().split("\n")
    if not lines:
        return ";"
    last_line = lines[-1].strip()

    if last_line.rstrip().endswith(">") and "PS " in last_line:
        return ";"  # PowerShell
    if last_line.rstrip().endswith(">") and ":\\" not in last_line[-60:]:
        return "&"  # CMD
    return ";"  # 默认 Unix shell


# ============================================================
# XshellController 主类
# ============================================================

class XshellController:
    """外部控制 Xshell 终端 — SendInput 写 + 剪贴板读"""

    def __init__(self, config=None):
        self._config = config
        self._target_hwnd = None
        self._terminal_hwnd = None
        self._separator = None

    # ── 生命周期 ──────────────────────────────────────

    def is_online(self) -> bool:
        return find_xshell_window() is not None

    def ensure_window(self):
        """确保找到 Xshell 窗口并缓存句柄"""
        hwnd = find_xshell_window()
        if hwnd is None:
            raise RuntimeError("找不到 Xshell 窗口，请先启动 Xshell")
        self._target_hwnd = hwnd
        self._terminal_hwnd = find_terminal_child(hwnd)
        return hwnd

    # ── 前台切换 ──────────────────────────────────────

    def _ensure_foreground(self) -> bool:
        if self._target_hwnd is None:
            self.ensure_window()
        return ensure_foreground(self._target_hwnd)

    # ── 写操作 ────────────────────────────────────────

    def send_text(self, text: str):
        self._ensure_foreground()
        send_text(text)

    def interrupt(self):
        """Ctrl+C"""
        self._ensure_foreground()
        _ctrl_key(VK_C)

    # ── 读操作 ────────────────────────────────────────

    def get_screen(self, lines=50) -> str:
        if self._target_hwnd is None:
            self.ensure_window()
        return copy_terminal_tail(self._target_hwnd, lines)

    # ── Shell 检测 ────────────────────────────────────

    def _get_separator(self) -> str:
        if self._separator is not None:
            return self._separator
        tail = self.get_screen(5)
        self._separator = detect_separator(tail)
        logger.info("Shell 分隔符: %s", self._separator)
        return self._separator

    # ── 命令执行 ──────────────────────────────────────

    def execute(self, command: str, marker: str, timeout: int = 30):
        """执行命令，等待 marker 出现，返回 (output, timed_out)"""
        self._ensure_foreground()
        clip = XshellClipboard()
        clip.save()

        try:
            sep = self._get_separator()
            full_cmd = command + " " + sep + " echo " + marker

            send_text(full_cmd + "\r")

            # 轮询 marker
            timed_out = True
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(0.5)
                tail = copy_terminal_tail(self._target_hwnd, 30)
                if marker in tail:
                    timed_out = False
                    break

            if timed_out:
                return "", True

            output = copy_terminal_all(self._target_hwnd)
            return output, False

        finally:
            clip.restore()

    def send_raw(self, text: str, wait_for: str = "$", timeout: int = 30):
        """发送原始文本（不追加回车），可选等待条件"""
        self._ensure_foreground()
        clip = XshellClipboard()
        clip.save()

        try:
            send_text(text)

            timed_out = True
            if wait_for:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    time.sleep(0.5)
                    tail = copy_terminal_tail(self._target_hwnd, 30)
                    if wait_for in tail:
                        timed_out = False
                        break
            else:
                timed_out = False

            output = copy_terminal_all(self._target_hwnd)
            return output, timed_out

        finally:
            clip.restore()
