"""xshell_controller.py 独立验证（不依赖 MCP 框架）"""
import sys
import time

sys.path.insert(0, "xshell-mcp/src")

from xshell_mcp.xshell_controller import (
    XshellController,
    find_xshell_window,
    find_terminal_child,
    ensure_foreground,
    XshellClipboard,
    copy_terminal_all,
    copy_terminal_tail,
    detect_separator,
)
from xshell_mcp.config import XshellConfig


def safe_line(line):
    """避免 GBK 编码错误"""
    return line.encode("ascii", errors="replace").decode("ascii")


def test_01_find_window():
    print("=" * 50)
    print("[TEST 1] Find Xshell Window")
    hwnd = find_xshell_window()
    if hwnd is None:
        print("  [SKIP] Xshell window not found, please start Xshell")
        return None
    print(f"  [PASS] Top-level window: 0x{hwnd:08X}")
    return hwnd


def test_02_find_terminal(hwnd):
    print("=" * 50)
    print("[TEST 2] Find Terminal Child")
    child = find_terminal_child(hwnd)
    if child is None:
        print("  [FAIL] No terminal child found")
        return None
    print(f"  [PASS] Terminal child: 0x{child:08X}")
    return child


def test_03_foreground(hwnd):
    print("=" * 50)
    print("[TEST 3] Foreground Switch")
    ok = ensure_foreground(hwnd)
    status = "PASS" if ok else "WARN"
    print(f"  [{status}] Foreground: {ok}")
    return ok


def test_04_send_text(hwnd):
    print("=" * 50)
    print("[TEST 4] SendInput Text")
    controller = XshellController()
    controller._target_hwnd = hwnd
    controller.send_text("echo test_from_controller\r")
    time.sleep(1)
    print("  [PASS] SendInput done (check Xshell window for typed characters)")


def test_05_clipboard_read(hwnd):
    print("=" * 50)
    print("[TEST 5] Clipboard Read")
    output = copy_terminal_tail(hwnd, 10)
    if not output:
        print("  [FAIL] Clipboard read returned empty")
        return False
    print(f"  [PASS] Read OK ({len(output)} chars)")
    for line in output.strip().split("\n")[-5:]:
        print(f"    | {safe_line(line)}")
    return True


def test_06_clipboard_save_restore():
    print("=" * 50)
    print("[TEST 6] Clipboard Save/Restore")
    clip = XshellClipboard()
    clip.save()
    saved_text = clip._saved_text
    preview = safe_line(saved_text[:80]) if saved_text else "(empty)"
    print(f"  Saved: {preview}")

    clip.restore()
    print("  [PASS] Clipboard restored")


def test_07_shell_detect():
    print("=" * 50)
    print("[TEST 7] Shell Separator Detection")
    cfg = XshellConfig()
    controller = XshellController(cfg)
    try:
        controller.ensure_window()
    except RuntimeError as e:
        print(f"  [SKIP] {e}")
        return None

    tail = controller.get_screen(5)
    sep = detect_separator(tail)
    print(f"  [PASS] Separator: '{sep}'")
    for line in tail.strip().split("\n")[-3:]:
        print(f"    | {safe_line(line)}")
    return sep


def test_08_full_execute():
    print("=" * 50)
    print("[TEST 8] Full Command Execute")
    cfg = XshellConfig()
    controller = XshellController(cfg)
    try:
        controller.ensure_window()
    except RuntimeError as e:
        print(f"  [SKIP] {e}")
        return

    output, timed_out = controller.execute(
        "echo full_test_marker", "__TEST_FULL_MARKER__", timeout=15
    )
    status = "FAIL" if timed_out else "PASS"
    print(f"  [{status}] timed_out={timed_out}, output_len={len(output)}")
    if not timed_out and output:
        for line in output.strip().split("\n")[-5:]:
            stripped = line.strip()
            if stripped:
                print(f"    | {safe_line(stripped)}")
    return not timed_out


def test_09_interrupt():
    print("=" * 50)
    print("[TEST 9] Interrupt Ctrl+C")
    cfg = XshellConfig()
    controller = XshellController(cfg)
    try:
        controller.ensure_window()
    except RuntimeError as e:
        print(f"  [SKIP] {e}")
        return

    controller.interrupt()
    time.sleep(0.5)
    print("  [PASS] Ctrl+C sent")


if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  XshellController Standalone Test")
    print("=" * 60)

    hwnd = test_01_find_window()
    if hwnd is None:
        print("\n  Please start Xshell first, then run this script.")
        sys.exit(0)

    test_02_find_terminal(hwnd)
    test_03_foreground(hwnd)
    test_04_send_text(hwnd)
    time.sleep(2)
    test_05_clipboard_read(hwnd)
    test_06_clipboard_save_restore()
    test_07_shell_detect()
    test_08_full_execute()
    test_09_interrupt()

    print()
    print("=" * 60)
    print("  Tests Complete")
    print("=" * 60)
