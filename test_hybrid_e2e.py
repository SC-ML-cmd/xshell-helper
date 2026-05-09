"""混合方案端到端测试：SendInput 写 + Bridge v8 读"""
import sys
import time

sys.path.insert(0, "xshell-mcp/src")

from xshell_mcp.xshell_controller import XshellController
from xshell_mcp.bridge_client import BridgeClient
from xshell_mcp.config import load_config
from xshell_mcp.output_processor import clean_command_output, truncate_output

config = load_config()
print(f"IPC dir: {config.ipc_dir}")
print(f"Timeout: {config.default_timeout}s")

# ── Step 1: 初始化 BridgeClient（IPC） ──
bridge = BridgeClient(config.ipc_dir, timeout=10)
bridge.initialize()

if bridge.check():
    print("[OK] Bridge v8 已在线")
else:
    print("[WAIT] Bridge v8 未就绪，请在 Xshell 中手动运行:")
    print(f"       工具 -> 脚本 -> 运行 -> {config.bridge_script_path}")
    print("       等待 Bridge 就绪...")
    for i in range(30):
        time.sleep(1)
        if bridge.check():
            print(f"[OK] Bridge v8 就绪 (等待 {i+1}s)")
            break
    else:
        print("[FAIL] Bridge 超时未就绪，测试终止")
        sys.exit(1)

# ── Step 2: 初始化 SendInput Controller ──
ctrl = XshellController(config)
if not ctrl.is_online():
    print("[FAIL] Xshell 窗口未找到")
    sys.exit(1)
ctrl.ensure_window()
print("[OK] Xshell 窗口已就绪")

# ── Step 3: 测试 execute_command (SendInput + Bridge) ──
print("\n" + "=" * 50)
print("[TEST] execute_command: echo hello_hybrid")
print("=" * 50)

marker = f"{config.marker_prefix}{int(time.time() * 1000000)}"
command = "echo hello_hybrid"

# 检测 shell 分隔符
screen_resp = bridge.get_screen(5)
last_line = screen_resp.output.strip().split("\n")[-1] if screen_resp.output else ""
sep = ";"  # default
if last_line.rstrip().endswith(">") and ":\\" not in last_line[-60:]:
    sep = "&" if "PS " not in last_line else ";"
print(f"Shell 分隔符: {sep!r}, 提示符: {last_line!r}")

# 用 SendInput 发送命令
full_cmd = f"{command} {sep} echo {marker}"
print(f"发送: {full_cmd}")
ctrl.send_text(full_cmd + "\r")

# 通过 Bridge 轮询 marker
print("轮询 marker...")
timed_out = True
deadline = time.time() + config.default_timeout
while time.time() < deadline:
    time.sleep(0.5)
    resp = bridge.get_screen(30)
    if marker in resp.output:
        timed_out = False
        print(f"[OK] Marker 检测到")
        break

if timed_out:
    print("[FAIL] 命令超时")
else:
    # 读取完整输出
    final = bridge.get_screen(500)
    clean = clean_command_output(final.output, command, marker)
    clean, truncated = truncate_output(clean)
    print(f"[PASS] 命令执行成功")
    print(f"  输出 ({len(clean)} chars):")
    for line in clean.strip().split("\n")[-5:]:
        safe = line.encode("ascii", errors="replace").decode("ascii")
        print(f"    | {safe}")

# ── Step 4: 测试 get_screen ──
print("\n" + "=" * 50)
print("[TEST] get_screen(10)")
print("=" * 50)
resp = bridge.get_screen(10)
print(f"screen_rows={resp.screen_rows}, screen_cols={resp.screen_cols}")
print(f"output ({len(resp.output)} chars):")
for line in resp.output.strip().split("\n")[-5:]:
    safe = line.encode("ascii", errors="replace").decode("ascii")
    print(f"  | {safe}")

print("\n" + "=" * 50)
print("混合方案测试完成!")
print("=" * 50)
