"""Xshell MCP Server — SendInput 写 + 最小化 Bridge 读"""

import time
import logging

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .bridge_client import BridgeClient
from .xshell_controller import XshellController
from .xshell_launcher import launch_xshell, wait_for_bridge
from .output_processor import clean_command_output, truncate_output

logger = logging.getLogger("xshell_mcp")

# ============================================================
# Server 初始化
# ============================================================

mcp = FastMCP("xshell-mcp")

_config = load_config()
_controller: XshellController | None = None
_bridge: BridgeClient | None = None


def get_controller() -> XshellController:
    global _controller
    if _controller is None:
        _controller = XshellController(_config)
    if not _controller.is_online():
        raise RuntimeError("Xshell 窗口未找到，请先启动 Xshell")
    return _controller


def get_bridge() -> BridgeClient:
    global _bridge
    if _bridge is None:
        _bridge = BridgeClient(_config.ipc_dir, timeout=_config.default_timeout)
        _bridge.initialize()
    if not _bridge.check():
        raise RuntimeError(
            "Bridge 未就绪。请在 Xshell 中运行 bridge/xshell_bridge_v8.py"
        )
    return _bridge


# ============================================================
# MCP 工具
# ============================================================

@mcp.tool()
def check_bridge() -> dict:
    """检查 Bridge 和 Xshell 状态"""
    controller_ok = _controller is not None and _controller.is_online()
    bridge_ok = _bridge is not None and _bridge.check() if _bridge else False
    return {
        "bridge_online": bridge_ok and controller_ok,
        "bridge_responds": bridge_ok,
        "controller_ready": controller_ok,
    }


@mcp.tool()
def execute_command(command: str, timeout: int = 30) -> dict:
    """在 Xshell 当前终端中执行命令并返回输出。

    命令通过键盘模拟在 Xshell 窗口中可见。请确保已在 Xshell 中
    手动完成登录和跳转（如需要），再使用此工具。

    Args:
        command: 要执行的 shell 命令
        timeout: 超时时间（秒），默认 30
    """
    controller = get_controller()
    bridge = get_bridge()
    marker = "{}{}".format(_config.marker_prefix, int(time.time() * 1000000))

    try:
        # 检测 shell 分隔符（通过 Bridge 读屏幕）
        screen_resp = bridge.get_screen(5)
        sep = _detect_separator_from_text(screen_resp.output)

        # 用 SendInput 键入命令（窗口可见）
        full_cmd = command.strip() + " " + sep + " echo " + marker
        controller.send_text(full_cmd + "\r")

        # 通过 Bridge 轮询 marker
        timed_out = True
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            resp = bridge.get_screen(30)
            if marker in resp.output:
                timed_out = False
                break

        if timed_out:
            return {
                "output": "",
                "timed_out": True,
                "truncated": False,
                "command": command,
            }

        # 读完整输出
        final = bridge.get_screen(resp.screen_rows - resp.start_row + 50)
        clean = clean_command_output(final.output, command.strip(), marker)
        clean, truncated = truncate_output(clean)

        return {
            "output": clean,
            "timed_out": False,
            "truncated": truncated,
            "command": command,
        }
    except Exception as e:
        return {
            "output": "",
            "timed_out": True,
            "truncated": False,
            "error": f"命令执行异常: {e}",
            "command": command,
        }


@mcp.tool()
def send_raw(text: str, wait_for: str = "$", timeout: int = 30) -> dict:
    """向 Xshell 终端发送原始文本，不自动追加回车。

    Args:
        text: 要发送的文本
        wait_for: 等待终端出现的字符串
        timeout: 超时时间（秒），默认 30
    """
    controller = get_controller()
    bridge = get_bridge()

    try:
        controller.send_text(text)

        timed_out = True
        if wait_for:
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(0.5)
                resp = bridge.get_screen(30)
                if wait_for in resp.output:
                    timed_out = False
                    break
        else:
            timed_out = False

        final = bridge.get_screen(500)
        output, truncated = truncate_output(final.output)

        return {
            "output": output,
            "timed_out": timed_out,
            "truncated": truncated,
        }
    except Exception as e:
        return {
            "output": "",
            "timed_out": True,
            "truncated": False,
            "error": f"send_raw 异常: {e}",
        }


@mcp.tool()
def interrupt() -> dict:
    """向终端发送 Ctrl+C，中断正在运行的命令"""
    controller = get_controller()
    try:
        controller.interrupt()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def get_screen(lines: int = 50) -> dict:
    """读取 Xshell 终端最后 N 行内容。"""
    bridge = get_bridge()
    try:
        resp = bridge.get_screen(lines=lines)
        output, truncated = truncate_output(resp.output)
        return {
            "content": output,
            "truncated": truncated,
            "screen_rows": resp.screen_rows,
            "screen_cols": resp.screen_cols,
        }
    except Exception as e:
        return {"content": "", "truncated": False, "error": str(e)}


@mcp.tool()
def get_session_info() -> dict:
    """获取当前 Xshell 终端状态信息"""
    try:
        bridge = get_bridge()
        resp = bridge.get_screen(lines=1)
        return {
            "screen_rows": resp.screen_rows,
            "screen_cols": resp.screen_cols,
        }
    except Exception as e:
        return {"screen_rows": 0, "screen_cols": 0, "error": str(e)}


# ============================================================
# 辅助
# ============================================================

def _detect_separator_from_text(tail_text: str) -> str:
    """从终端文本检测 shell 分隔符"""
    lines = tail_text.strip().split("\n")
    if not lines:
        return ";"
    last_line = lines[-1].strip()
    if last_line.rstrip().endswith(">") and "PS " in last_line:
        return ";"
    if last_line.rstrip().endswith(">") and ":\\" not in last_line[-60:]:
        return "&"
    return ";"


# ============================================================
# 启动逻辑
# ============================================================

def init_controller() -> tuple:
    global _controller, _bridge

    controller = XshellController(_config)
    bridge = BridgeClient(_config.ipc_dir, timeout=_config.default_timeout)
    bridge.initialize()

    # 检查现有状态
    if controller.is_online() and bridge.check():
        logger.info("Xshell 和 Bridge 均在线")
        _controller = controller
        _bridge = bridge
        return controller, bridge

    # 启动 Xshell + Bridge
    logger.info("启动 Xshell 并加载 Bridge 脚本...")
    launch_xshell(_config)

    logger.info("等待 Bridge 就绪...")
    if not wait_for_bridge(bridge):
        raise RuntimeError(
            "Bridge 启动超时。请手动在 Xshell 中: "
            "工具 → 脚本 → 运行 → bridge/xshell_bridge_v8.py"
        )

    if not controller.is_online():
        controller.ensure_window()

    _controller = controller
    _bridge = bridge
    logger.info("混合模式就绪: SendInput + Bridge v8")
    return controller, bridge
