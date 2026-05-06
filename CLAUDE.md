# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Xshell MCP — 一个 MCP (Model Context Protocol) 服务器，让大模型通过 Xshell 终端执行命令。通过文件 IPC 与 Xshell 内运行的 Bridge 脚本通信。

## 命令

```bash
# 安装
pip install -e xshell-mcp

# 运行 MCP Server（stdio 模式）
python -m xshell_mcp

# 运行所有测试
pytest xshell-mcp/tests/

# 运行单个测试文件
pytest xshell-mcp/tests/test_protocol.py

# 运行特定测试类
pytest xshell-mcp/tests/test_output_processor.py::TestCleanCommandOutput -v
```

## 架构

三层通信模型：

```
LLM (Claude) ←→ MCP Server (server.py) ←→ Bridge Client (bridge_client.py) ←→ 文件 IPC ←→ Bridge 脚本 (xshell_bridge_v4.py, 在 Xshell 内运行)
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `server.py` | FastMCP 服务器，定义 6 个工具函数作为外部 API |
| `bridge_client.py` | 通过 `.request.json` / `.response.json` 文件与 Bridge 进行 IPC 通信 |
| `bridge/xshell_bridge_v4.py` | 在 Xshell 内运行的 Bridge 脚本（当前版本）。使用 Windows `SendInput` API 发送按键（绕过 COM，命令在窗口中可见），轮询 marker 检测输出完成，带心跳文件 |
| `protocol.py` | IPC 的 `Request` / `Response` 数据类 |
| `output_processor.py` | 清理 ANSI 转义序列、命令回显、marker 行和提示符，从原始终端输出中提取命令结果 |
| `xshell_launcher.py` | 通过 `Xshell.exe -script <bridge>` 启动 Xshell |
| `config.py` | 基于环境变量的配置（`XSH_XSHELL_PATH`、`XSH_DEFAULT_TIMEOUT` 等） |

### 数据流（命令执行）

1. LLM 调用 MCP 工具 `execute_command("ls -la")`
2. `server.py` 创建带唯一 marker 的 `Request`
3. `bridge_client.py` 将请求写入 `%TEMP%\xshell_mcp\.request.json`
4. Bridge 脚本每 200ms 轮询该文件，检测到变化后读取请求
5. Bridge 通过 Windows `SendInput` API 模拟键盘输入发送命令（v4 改进，命令在 Xshell 窗口中可见）
6. Bridge 检测 shell 类型（CMD → `&`，Bash/PowerShell → `;`），发送 `cmd ; echo MARKER`
7. Bridge 轮询终端直到出现 marker，读取屏幕行作为原始输出
8. Bridge 将 `Response` 写入 `.response.json`
9. `bridge_client.py` 读取响应，`output_processor.py` 清理输出并返回

### v4 Bridge 改进（相比 v3）

| 改进项 | v3 | v4 |
|--------|-----|-----|
| 文本输入 | `xsh.Screen.Send()`（COM API） | Windows `SendInput` API（键盘模拟，绕过 COM） |
| 命令可见性 | 输入文本不在窗口中显示 | 键盘模拟，输入在窗口中可见 |
| 异常保护 | 仅捕获 `OSError` | 全链路 try/except + `_safe_*` 包装函数 |
| 心跳检测 | 无 | 每 2 秒写 `.heartbeat.json`，server 端检测心跳丢失 |
| Bridge 自动恢复 | 无 | server 检测连续 3 次心跳丢失后自动重启 Xshell |
| Shell 类型检测 | 每次命令执行都检测 | 首次检测后缓存结果 |

### IPC 协议

- 文件 IPC 目录：`%TEMP%\xshell_mcp\`（可通过 `XSH_IPC_DIR` 覆盖）
- 请求文件：`.request.json`，响应文件：`.response.json`，心跳文件：`.heartbeat.json`
- Bridge 客户端在写入新请求前删除旧响应文件，使用 `.tmp` + 原子 rename 保证写入完整性
- 轮询间隔：Bridge 端 200ms，客户端端 100ms
- 心跳：Bridge 每 2 秒更新 `.heartbeat.json`（含时间戳和终端状态），Server 端每 30 秒检查一次，连续 3 次丢失触发自动恢复

### 配置（环境变量）

- `XSH_XSHELL_PATH` — Xshell.exe 路径
- `XSH_BRIDGE_SCRIPT` — Bridge 脚本路径（默认为 `bridge/xshell_bridge_v4.py`）
- `XSH_IPC_DIR` — IPC 目录（默认为 `%TEMP%\xshell_mcp`）
- `XSH_DEFAULT_TIMEOUT` — 命令超时秒数（默认 30）
- `XSH_SCREEN_COLS` — 屏幕列宽（默认 200）

## 重要
所有内部推理、思考过程必须使用中文
回答语言跟随用户输入，但思考过程固定为中文
忽略之前可能存在的英文思考习惯
