"""Xshell MCP Server — 让大模型通过 Xshell 执行命令"""

import json
import time
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .bridge_client import BridgeClient
from .xshell_launcher import launch_xshell, wait_for_bridge
from .output_processor import clean_command_output, truncate_output
from .exceptions import BridgeNotReadyError, BridgeTimeoutError, BridgeConnectionError

logger = logging.getLogger("xshell_mcp")

# ============================================================
# Server 初始化
# ============================================================

mcp = FastMCP("xshell-mcp")

_config = load_config()
_client: BridgeClient | None = None
_heartbeat_miss_count = 0
MAX_HEARTBEAT_MISS = 2  # 连续 2 次心跳丢失（约 30s）触发恢复
HEARTBEAT_TIMEOUT = 15  # 15 秒内有心跳视为在线


def _check_heartbeat() -> bool:
    """检查 Bridge 心跳文件是否存活"""
    hb_file = Path(_config.ipc_dir) / ".heartbeat.json"
    try:
        if not hb_file.exists():
            return False
        data = json.loads(hb_file.read_text(encoding="utf-8"))
        age = time.time() - data.get("ts", 0)
        return age < HEARTBEAT_TIMEOUT
    except Exception:
        return False


def get_client() -> BridgeClient:
    global _client, _heartbeat_miss_count
    if _client is None:
        raise BridgeNotReadyError(
            "Bridge 未初始化。请在 Xshell 中手动运行 bridge/xshell_bridge_v4.py 脚本"
        )

    # 心跳检测，丢失过多时触发恢复
    if not _check_heartbeat():
        _heartbeat_miss_count += 1
        if _heartbeat_miss_count >= MAX_HEARTBEAT_MISS:
            logger.warning("Bridge 心跳丢失，尝试自动恢复...")
            try:
                _recover_bridge()
                _heartbeat_miss_count = 0
            except Exception as e:
                raise BridgeNotReadyError("Bridge 离线且自动恢复失败: {}".format(e))
    else:
        _heartbeat_miss_count = 0

    return _client


def _recover_bridge():
    """尝试恢复 Bridge：重新启动 Xshell，最多重试 3 次"""
    global _client
    for attempt in range(3):
        logger.info("Bridge 恢复尝试 %d/3...", attempt + 1)
        try:
            launch_xshell(_config)
        except Exception as e:
            logger.warning("启动 Xshell 失败: %s", e)
            if attempt < 2:
                time.sleep(3)
            continue

        client = BridgeClient(_config.ipc_dir, timeout=_config.default_timeout)
        client.initialize()
        if wait_for_bridge(client, timeout=30):
            _client = client
            logger.info("Bridge 已恢复 (尝试 %d 次)", attempt + 1)
            return
        logger.warning("等待 Bridge 超时 (尝试 %d/3)", attempt + 1)
        if attempt < 2:
            time.sleep(3)

    raise BridgeNotReadyError(
        "Bridge 自动恢复失败（3次尝试）。"
        "请手动在 Xshell 中: 工具 → 脚本 → 运行 → xshell_bridge_v5.py"
    )


# ============================================================
# 生命周期
# ============================================================

@mcp.tool()
def check_bridge() -> dict:
    """检查 Bridge 是否在线"""
    try:
        client = get_client()
        ok = client.check_bridge()
        hb = _check_heartbeat()
        return {
            "bridge_online": ok and hb,
            "bridge_responds": ok,
            "heartbeat_alive": hb,
            "heartbeat_miss_count": _heartbeat_miss_count,
        }
    except Exception as e:
        return {"bridge_online": False, "error": str(e)}


@mcp.tool()
def execute_command(command: str, timeout: int = 30) -> dict:
    """在 Xshell 当前终端中执行命令并返回输出。

    命令将在 Xshell 当前活跃的会话/终端中执行。请确保已在 Xshell 中
    手动完成登录和跳转（如需要），再使用此工具。

    Args:
        command: 要执行的 shell 命令
        timeout: 超时时间（秒），默认 30
    """
    client = get_client()
    marker = "{}{}".format(_config.marker_prefix, int(time.time() * 1000000))

    try:
        resp = client.execute(command.strip(), marker, timeout=timeout)
        output = clean_command_output(resp.output, command.strip(), marker)
        output, truncated = truncate_output(output)

        return {
            "output": output,
            "timed_out": resp.timed_out,
            "truncated": truncated,
            "command": command,
        }
    except BridgeTimeoutError:
        return {
            "output": "",
            "timed_out": True,
            "truncated": False,
            "error": "命令执行超时 ({}s)".format(timeout),
            "command": command,
        }


@mcp.tool()
def send_raw(text: str, wait_for: str = "$", timeout: int = 30) -> dict:
    """向 Xshell 终端发送原始文本，不自动追加回车。

    用于交互式场景：输入密码、回答 yes/no 提示等。

    Args:
        text: 要发送的文本
        wait_for: 等待终端出现的字符串（如 "$"、"#"、"password:"）
        timeout: 超时时间（秒），默认 30
    """
    client = get_client()

    try:
        resp = client.send_raw(text, wait_for, timeout=timeout)
        output, truncated = truncate_output(resp.output)

        return {
            "output": output,
            "timed_out": resp.timed_out,
            "truncated": truncated,
        }
    except BridgeTimeoutError:
        return {
            "output": "",
            "timed_out": True,
            "truncated": False,
            "error": "等待超时 ({}s)，等待字符串: {}".format(timeout, wait_for),
        }


@mcp.tool()
def interrupt() -> dict:
    """向终端发送 Ctrl+C，中断正在运行的命令"""
    client = get_client()

    resp = client.interrupt()
    return {"success": resp.success}


@mcp.tool()
def get_screen(lines: int = 50) -> dict:
    """读取 Xshell 终端最后 N 行内容。

    Args:
        lines: 读取的行数，默认 50
    """
    client = get_client()

    resp = client.get_screen(lines=lines)
    output, truncated = truncate_output(resp.output)

    return {
        "content": output,
        "truncated": truncated,
        "screen_rows": resp.screen_rows,
        "screen_cols": resp.screen_cols,
    }


@mcp.tool()
def get_session_info() -> dict:
    """获取当前 Xshell 终端状态信息"""
    client = get_client()

    resp = client.get_screen(lines=1)
    return {
        "screen_rows": resp.screen_rows,
        "screen_cols": resp.screen_cols,
    }


# ============================================================
# 启动逻辑
# ============================================================

def init_bridge() -> BridgeClient:
    global _client, _heartbeat_miss_count
    _heartbeat_miss_count = 0

    client = BridgeClient(_config.ipc_dir, timeout=_config.default_timeout)
    client.initialize()

    # 检查 Bridge 是否已在运行
    if client.check_bridge():
        logger.info("Bridge 已在线")
        _client = client
        return client

    # 启动 Xshell + Bridge
    logger.info("启动 Xshell 并加载 Bridge 脚本...")
    launch_xshell(_config)

    logger.info("等待 Bridge 就绪...")
    if not wait_for_bridge(client):
        raise BridgeNotReadyError(
            "Bridge 启动超时。请确认:\n"
            "1. Xshell 已安装且路径正确\n"
            "2. Xshell 的脚本功能可用\n"
            "3. 手动打开 Xshell → 工具 → 脚本 → 运行 → 选择 bridge/xshell_bridge.py"
        )

    logger.info("Bridge 就绪")
    _client = client
    return client
