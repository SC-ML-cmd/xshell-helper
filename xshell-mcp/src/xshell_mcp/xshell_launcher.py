"""启动 Xshell 并加载 Bridge v8 脚本"""

import subprocess
import time
from pathlib import Path

from .config import XshellConfig
from .bridge_client import BridgeClient


def find_xshell(config: XshellConfig) -> str:
    path = config.xshell_path
    if path and Path(path).exists():
        return path

    candidates = [
        r"D:\software\xshell8\Xshell.exe",
        r"C:\Program Files\NetSarang\Xshell 8\Xshell.exe",
        r"C:\Program Files (x86)\NetSarang\Xshell 8\Xshell.exe",
        r"C:\Program Files\NetSarang\Xshell 7\Xshell.exe",
        r"C:\Program Files (x86)\NetSarang\Xshell 7\Xshell.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def _find_session(config: XshellConfig) -> str:
    if config.session_path and Path(config.session_path).exists():
        return config.session_path

    applog_dir = Path.home() / "Documents" / "NetSarang Computer" / "8" / "Xshell" / "applog"
    if applog_dir.is_dir():
        log_files = sorted(
            applog_dir.glob("XshellCore_*.log"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        for log in log_files[:3]:
            try:
                content = log.read_text(encoding="utf-16-le", errors="ignore")
                for line in content.split("\n"):
                    if "Load profile(Session)" in line and ".xsh" in line:
                        start = line.find("C:\\")
                        if start >= 0:
                            path_str = line[start:].strip()
                            if Path(path_str).exists():
                                return path_str
            except Exception:
                pass

    sessions_dir = Path.home() / "Documents" / "NetSarang Computer" / "8" / "Xshell" / "Sessions"
    if sessions_dir.is_dir():
        xsh_files = sorted(
            sessions_dir.glob("*.xsh"),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if xsh_files:
            return str(xsh_files[0])

    return ""


def launch_xshell(config: XshellConfig) -> bool:
    xshell_exe = find_xshell(config)
    if not xshell_exe:
        raise FileNotFoundError("找不到 Xshell.exe，请设置 XSH_XSHELL_PATH 环境变量")

    bridge_script = config.bridge_script_path
    if not Path(bridge_script).exists():
        raise FileNotFoundError(f"找不到 Bridge 脚本: {bridge_script}")

    # 杀掉旧进程
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "XshellCore.exe"],
            capture_output=True, timeout=10,
        )
        time.sleep(1)
    except Exception:
        pass

    cmd = [xshell_exe]
    session = _find_session(config)
    if session:
        cmd.append(session)
    cmd.extend(["-script", bridge_script])
    subprocess.Popen(cmd, cwd=str(Path(xshell_exe).parent))
    return True


def wait_for_bridge(client: BridgeClient, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.check():
            return True
        time.sleep(0.5)
    return False
