"""临时测试脚本：启动 Xshell"""
import subprocess, time, os

xshell = r"D:\software\xshell8\Xshell.exe"
session = r"C:\Users\Administrator\Documents\NetSarang Computer\8\Xshell\Sessions\ali_ecs_0103.xsh"
bridge = r"D:\dev\workspace\AI\xshell-helper\xshell-mcp\bridge\xshell_bridge_v5.py"

# 杀旧进程
subprocess.run(["taskkill", "/f", "/im", "XshellCore.exe"], capture_output=True)
subprocess.run(["taskkill", "/f", "/im", "Xshell.exe"], capture_output=True)
time.sleep(2)

# 启动
cmd = [xshell, session, "-script", bridge]
print("CMD:", cmd)
p = subprocess.Popen(cmd, cwd=os.path.dirname(xshell))
print("PID:", p.pid)

# 等 15 秒
for i in range(15):
    time.sleep(1)
    if os.path.exists(r"C:\Users\Administrator\AppData\Local\Temp\xshell_mcp\.bridge_startup.txt"):
        print(f"[{i+1}s] bridge_startup.txt found!")
        break
    if os.path.exists(r"C:\Users\Administrator\AppData\Local\Temp\xshell_mcp\.heartbeat.json"):
        print(f"[{i+1}s] heartbeat found!")
    if i % 5 == 4:
        print(f"[{i+1}s] waiting...")

print("Done. Check Xshell window.")
