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
LLM (Claude) ←→ MCP Server (server.py) ←→ Bridge Client (bridge_client.py) ←→ 文件 IPC ←→ Bridge 脚本 (xshell_bridge_v7.py, 在 Xshell 内运行)
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `server.py` | FastMCP 服务器，定义 6 个工具函数作为外部 API |
| `bridge_client.py` | 通过 `.request.json` / `.response.json` 文件与 Bridge 进行 IPC 通信 |
| `bridge/xshell_bridge_v7.py` | **当前版本**。在 Xshell 内运行的 Bridge 脚本。使用 `xsh.Screen.Send()` 发送命令，`_safe_sleep()` 策略解决崩溃与卡死问题 |
| `protocol.py` | IPC 的 `Request` / `Response` 数据类 |
| `output_processor.py` | 清理 ANSI 转义序列、命令回显、marker 行和提示符，从原始终端输出中提取命令结果 |
| `xshell_launcher.py` | 通过 `Xshell.exe -script <bridge>` 启动 Xshell |
| `config.py` | 基于环境变量的配置（`XSH_XSHELL_PATH`、`XSH_DEFAULT_TIMEOUT` 等） |

## Bridge 版本演进

### v3 — 原始可用版本
- `xsh.Session.Sleep(200)` 主循环，事件循环正常运行
- `xsh.Screen.Send()` 发送命令
- 问题：SSH 断开后，`Session.Sleep()` 在废弃 COM 对象上调用 ~90,000 次（5 小时空闲），触发 native Access Violation → XShell 进程崩溃
- 无心跳、无自动恢复

### v4 — SendInput 尝试（失败）
- 引入 Windows `SendInput` API 模拟键盘输入，试图让命令在窗口中可见
- 引入心跳文件、全面异常捕获
- **失败原因 1**：Xshell 嵌入式 Python 缺少 `_ctypes.pyd`，`import ctypes` 失败
- **失败原因 2**：从 Xshell 进程内部调用 `SendInput` 向自己窗口发送按键 → 可重入 COM 回调 → 死锁，Xshell 卡死

### v5 — Screen.Send + time.sleep（失败）
- 回退到 `xsh.Screen.Send()`，但将所有 `Session.Sleep()` 替换为 `time.sleep()`
- **失败原因**：`time.sleep()` 阻塞 XShell UI 主线程的消息泵，`Screen.Send()` 字符卡在缓冲区，命令永远无法到达 SSH 通道 → 超时

### v6 — 与 v5 相同问题
- 与 v5 相同的 `time.sleep()` 策略，同样命令超时、Xshell 卡死

### v7 — 当前版本（_safe_sleep 策略）
- **核心发现**：Xshell 在 UI 主线程上运行 Python 脚本
  - `xsh.Session.Sleep(ms)` = 内部运行 Xshell 事件循环 → UI 响应、SSH 数据正常传输
  - `time.sleep(ms)` = 阻塞 GIL、冻结消息泵 → Screen.Send 无法传输、屏幕冻结
- **`_safe_sleep()` 策略**：
  - `Session.Connected == True` → 用 `xsh.Session.Sleep(200)`（事件循环运行，Screen.Send 才能工作）
  - 其他情况（断开/COM 异常）→ 用 `time.sleep(0.2)`（安全，不会 native crash）
  - 同时解决：命令执行有效（连接时走事件循环）+ 长期运行不崩溃（断开后 fallback）

### Bridge 版本对比

| 特性 | v3 | v4 | v5/v6 | v7 (当前) |
|------|-----|-----|-------|-----------|
| 文本输入 | Screen.Send | SendInput(死锁) | Screen.Send | Screen.Send |
| 休眠方式 | Session.Sleep | time.sleep | time.sleep | **_safe_sleep** |
| 命令执行 | ✓ 有效 | ✗ 死锁 | ✗ 超时 | ✓ 有效 |
| 长期稳定 | ✗ 5h后崩溃 | ✗ 卡死 | ✗ 卡死 | ✓ |
| 心跳检测 | ✗ | ✓ | ✓ | ✓ |
| 自动恢复 | ✗ | ✓ | ✓ | ✓ |

## 数据流（命令执行）

1. LLM 调用 MCP 工具 `execute_command("ls -la")`
2. `server.py` 创建带唯一 marker 的 `Request`
3. `bridge_client.py` 将请求原子写入 `%TEMP%\xshell_mcp\.request.json`
4. Bridge 脚本每 200ms 轮询该文件（`os.path.getmtime`），检测到变化后读取请求
5. Bridge 通过 `_safe_sleep(200)` 保持事件循环活跃，`xsh.Screen.Send()` 发送命令
6. Bridge 检测 shell 类型（CMD → `&`，Bash/PowerShell → `;`，首次检测后缓存），拼接 `cmd ; echo MARKER`
7. Bridge 用 `_safe_sleep(200)` 轮询终端直到出现 marker，通过 `xsh.Screen.Get()` 读取屏幕行
8. Bridge 将 `Response` 原子写入 `.response.json`
9. `bridge_client.py` 读取响应，`output_processor.py` 清理输出并返回

## IPC 协议

- 文件 IPC 目录：`%TEMP%\xshell_mcp\`（可通过 `XSH_IPC_DIR` 覆盖）
- 请求文件：`.request.json`，响应文件：`.response.json`，心跳文件：`.heartbeat.json`
- 所有写入使用 `.tmp` + `os.replace()` 保证原子性
- 轮询间隔：Bridge 端 200ms，客户端端 100ms
- 心跳：Bridge 每 2 秒更新 `.heartbeat.json`（纯文件 I/O，零 COM），含时间戳和终端状态

## 配置（环境变量）

- `XSH_XSHELL_PATH` — Xshell.exe 路径（默认 `D:\software\xshell8\Xshell.exe`）
- `XSH_BRIDGE_SCRIPT` — Bridge 脚本路径（默认为 `bridge/xshell_bridge_v7.py`）
- `XSH_IPC_DIR` — IPC 目录（默认为 `%TEMP%\xshell_mcp`）
- `XSH_XSHELL_SESSION` — Xshell 会话文件路径（.xsh），用于自动恢复时重建 SSH 连接
- `XSH_DEFAULT_TIMEOUT` — 命令超时秒数（默认 30）
- `XSH_SCREEN_COLS` — 屏幕列宽（默认 200）

## Bridge 自动恢复

Server 通过心跳文件检测 Bridge 存活：
- Bridge 每 2 秒更新 `.heartbeat.json`（纯文件 I/O，零 COM）
- Server 每 500ms 检查一次，15 秒无心跳视为离线
- 连续 2 次心跳丢失（约 30s）触发自动恢复
- 恢复流程：启动 Xshell → 加载会话文件 → 自动 SSH 连接 → 运行 Bridge 脚本
- 最多重试 3 次，每次等 3 秒

会话文件查找顺序：
1. 环境变量 `XSH_XSHELL_SESSION` 指定的路径
2. `Documents\NetSarang Computer\8\Xshell\Sessions\` 下最近修改的 .xsh 文件

## 已知问题

1. **Xshell 8.0.0021 的 CrashRpt.dll（1.4.0.2）存在崩溃 bug**。SSH 断开后，在废弃 Session COM 对象上反复调用方法会累积 corruption，最终在 CrashRpt.dll 内部触发 native Access Violation。Python `except Exception` 无法捕获。v7 通过 `_safe_sleep()` 在 SSH 断开后避免调用 `Session.Sleep()` 来绕过。

2. **Screen.Send() 命令不可见**。`xsh.Screen.Send()` 直接注入 SSH 通道，绕过 Xshell GUI 渲染管线，命令不会在窗口中显示。服务器端 echo 会将命令回显到终端输出中，但本地用户看不到输入过程。`SendInput` 方案能解决可见性但在进程内会死锁。这是 Xshell COM API 的局限性，暂时没有好的解决办法。

3. **Xshell 嵌入式 Python 不完整**。`python38.zip` 缺少 `_ctypes.pyd` 等 C 扩展，`import ctypes` 会失败。Bridge 脚本不能依赖 ctypes。

## 重要
所有内部推理、思考过程必须使用中文
回答语言跟随用户输入，但思考过程固定为中文
忽略之前可能存在的英文思考习惯
