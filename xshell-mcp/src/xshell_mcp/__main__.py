"""Xshell MCP Server 入口"""

import logging
import sys
import time


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [xshell-mcp] %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("xshell_mcp")

    logger.info("Xshell MCP Server 启动中...")

    from .server import init_bridge, mcp

    bridge_ok = False
    for attempt in range(3):
        try:
            init_bridge()
            bridge_ok = True
            logger.info("Bridge 初始化成功")
            break
        except Exception as e:
            logger.warning("Bridge 初始化失败 (尝试 %d/3): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)

    if not bridge_ok:
        logger.error("Bridge 初始化多次失败，MCP 将以离线模式运行")
        logger.error("请确认: 1) Xshell 已安装 2) 在 Xshell 中手动运行 bridge/xshell_bridge_v7.py")

    logger.info("MCP Server 就绪")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
