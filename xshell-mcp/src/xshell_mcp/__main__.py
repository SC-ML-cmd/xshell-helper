"""Xshell MCP Server 入口 — SendInput 写 + Bridge v8 读"""

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

    logger.info("Xshell MCP Server 启动中（混合模式：SendInput + Bridge v8）...")

    from .server import init_controller, mcp

    ok = False
    for attempt in range(3):
        try:
            init_controller()
            ok = True
            logger.info("初始化成功")
            break
        except Exception as e:
            logger.warning("初始化失败 (尝试 %d/3): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)

    if not ok:
        logger.error("初始化多次失败，MCP 将以离线模式运行")
        logger.error("请确认: 1) Xshell 已启动 2) Bridge v8 脚本已运行")

    logger.info("MCP Server 就绪")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
