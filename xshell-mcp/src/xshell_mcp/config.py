from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class XshellConfig:
    xshell_path: str = r"D:\software\xshell8\Xshell.exe"
    bridge_script_path: str = ""
    session_path: str = ""  # .xsh 会话文件，用于自动恢复时重建 SSH 连接
    ipc_dir: str = ""
    default_timeout: int = 30
    screen_cols: int = 200
    marker_prefix: str = "__XSH_"

    def __post_init__(self):
        if not self.bridge_script_path:
            pkg_dir = Path(__file__).resolve().parent.parent.parent
            self.bridge_script_path = str(pkg_dir / "bridge" / "xshell_bridge_v5.py")
        if not self.ipc_dir:
            import tempfile
            self.ipc_dir = str(Path(tempfile.gettempdir()) / "xshell_mcp")


def load_config() -> XshellConfig:
    import os

    cfg = XshellConfig()
    if v := os.getenv("XSH_XSHELL_PATH"):
        cfg.xshell_path = v
    if v := os.getenv("XSH_BRIDGE_SCRIPT"):
        cfg.bridge_script_path = v
    if v := os.getenv("XSH_XSHELL_SESSION"):
        cfg.session_path = v
    if v := os.getenv("XSH_IPC_DIR"):
        cfg.ipc_dir = v
    if v := os.getenv("XSH_DEFAULT_TIMEOUT"):
        cfg.default_timeout = int(v)
    if v := os.getenv("XSH_SCREEN_COLS"):
        cfg.screen_cols = int(v)
    return cfg
