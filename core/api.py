"""PythonApi：暴露给前端 JS 的全部方法（pywebview js_api）。

前端通过 window.pywebview.api.<method>(args) 调用。
所有方法返回 dict/list/str/bool 等可 JSON 序列化的对象。
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import threading
import urllib.request
import webbrowser
import zipfile
from typing import Any, Optional

import json
from datetime import datetime
from core.backup import BackupManager
from core.config_store import ConfigStore
from core.shield_runner import ShieldRunner


# 本 GUI 版本号（用于更新检测）
# 内置兜底版本号（pyproject.toml 不可读时使用，CI 构建时自动同步）
_FALLBACK_VERSION = "1.0.0"


def _read_gui_version() -> str:
    """从 pyproject.toml 读取版本号，兜底 _FALLBACK_VERSION。
    兼容源码运行（core/../pyproject.toml）和 PyInstaller 打包运行（sys._MEIPASS）。"""
    try:
        base = getattr(sys, "_MEIPASS", None)
        if not base:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pp = os.path.join(base, "pyproject.toml")
        if os.path.isfile(pp):
            with open(pp, encoding="utf-8") as f:
                m = re.search(r'^version\s*=\s*"(.+?)"', f.read(), re.M)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return _FALLBACK_VERSION


GUI_VERSION = _read_gui_version()

# 协议元信息（端口、是否需要认证、说明）
PROTOCOLS = {
    "ssh": {
        "port": 22,
        "auth": True,
        "label": "SSH",
        "desc": "浏览器中打开完整 SSH 终端，支持私钥/SFTP",
    },
    "rdp": {
        "port": 3389,
        "auth": True,
        "label": "RDP",
        "desc": "浏览器中访问 Windows 远程桌面",
    },
    "vnc": {
        "port": 5900,
        "auth": True,
        "label": "VNC",
        "desc": "浏览器中共享和控制远程桌面屏幕",
    },
    "http": {
        "port": 80,
        "auth": False,
        "label": "HTTP",
        "desc": "将本地/内网 HTTP Web 应用暴露到公网",
    },
    "https": {
        "port": 443,
        "auth": False,
        "label": "HTTPS",
        "desc": "将本地/内网 HTTPS Web 应用暴露到公网",
    },
    "telnet": {
        "port": 23,
        "auth": True,
        "label": "Telnet",
        "desc": "连接网络设备与传统 Telnet 服务",
    },
    "tcp": {
        "port": 0,
        "auth": False,
        "label": "TCP",
        "desc": "TCP 端口代理（MySQL/Redis 等数据库）",
    },
    "udp": {"port": 0, "auth": False, "label": "UDP", "desc": "UDP 端口代理（DNS 等）"},
}

# 插件协议（数据库类）
PLUGIN_PROTOCOLS = {"mysql", "postgres", "sqlserver"}


class PythonApi:
    def __init__(self):
        self.shield_exe = _locate_shield()
        self.runner = ShieldRunner(self.shield_exe) if self.shield_exe else None
        self.store = ConfigStore(self.shield_exe) if self.shield_exe else None
        self._window = None
        # Web UI 后台进程管理（shield start 长驻进程）
        self._web_ui_process: Optional[subprocess.Popen] = None
        self._web_ui_lock = threading.Lock()
        self._window_visible = True  # 手动追踪，比 _window.hidden 更可靠
        self._backup_mgr = BackupManager(on_notify=self._backup_notify)

    def attach_window(self, window) -> None:
        self._window = window

    # ---------- 环境与版本 ----------

    def get_env(self) -> dict:
        """返回 shield 路径、版本、官方配置目录、可用协议。"""
        if not self.shield_exe:
            return {
                "installed": False,
                "error": "未找到 shield.exe",
                "gui_version": GUI_VERSION,
            }
        version = ""
        # shield 用 --version flag 输出版本（裸 `version` 子命令会报错）
        ver_res = self.runner.run_cli(["--version"], timeout=10)
        for line in (
            ver_res.get("stdout", "") + ver_res.get("stderr", "")
        ).splitlines():
            line = line.strip()
            # 形如 "shield version 0.3.11"
            if "version" in line.lower() and not line.startswith("Usage"):
                version = line
                break
            if line and not line.startswith("Usage") and not line.startswith("Error"):
                version = line
                break
        return {
            "installed": True,
            "path": self.shield_exe,
            "version": version,
            "gui_version": GUI_VERSION,
            "config": self.store.status() if self.store else None,
            "protocols": PROTOCOLS,
        }

    # ---------- 更新检测 ----------

    def check_updates(self) -> dict:
        """检测 GUI 和 Shield CLI 是否有新版本。
        返回：
          gui: { has_update, latest_version, download_url }
          shield: { has_update, latest_version, download_url }
        """
        result = {
            "gui": {"has_update": False, "latest_version": "", "download_url": ""},
            "shield": {"has_update": False, "latest_version": "", "download_url": ""},
        }
        # 检测 GUI 更新（shield-gui GitHub Release）
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/pcoof/shield-gui/releases/latest",
                headers={
                    "User-Agent": "ShieldGUI",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                latest = data.get("tag_name", "").lstrip("v")
                current = GUI_VERSION
                if latest and _compare_versions(latest, current) > 0:
                    zip_url = ""
                    for asset in data.get("assets", []):
                        if (
                            asset.get("name", "").endswith(".exe")
                            or asset.get("name") == "ShieldGUI.exe"
                        ):
                            zip_url = asset.get("browser_download_url", "")
                            break
                    result["gui"] = {
                        "has_update": True,
                        "latest_version": latest,
                        "current_version": current,
                        "download_url": zip_url or data.get("html_url", ""),
                        "release_url": data.get("html_url", ""),
                    }
        except Exception:
            pass
        # 检测 Shield CLI 更新
        try:
            current_shield = ""
            if self.shield_exe:
                ver_res = self.runner.run_cli(["--version"], timeout=5)
                for line in (
                    ver_res.get("stdout", "") + ver_res.get("stderr", "")
                ).splitlines():
                    m = re.search(r"(\d+\.\d+\.\d+)", line)
                    if m:
                        current_shield = m.group(1)
                        break
            req = urllib.request.Request(
                "https://api.github.com/repos/fengyily/shield-cli/releases/latest",
                headers={
                    "User-Agent": "ShieldGUI",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                latest = data.get("tag_name", "").lstrip("v")
                if (
                    current_shield
                    and latest
                    and _compare_versions(latest, current_shield) > 0
                ):
                    zip_url = ""
                    for asset in data.get("assets", []):
                        name = asset.get("name", "")
                        if "windows" in name.lower() and name.endswith(".zip"):
                            zip_url = asset.get("browser_download_url", "")
                            break
                    result["shield"] = {
                        "has_update": True,
                        "latest_version": latest,
                        "current_version": current_shield,
                        "download_url": zip_url or "",
                        "release_url": data.get("html_url", ""),
                    }
        except Exception:
            pass
        return result

    def get_gui_version(self) -> str:
        return GUI_VERSION

    # ---------- 窗口控制（frameless 模式） ----------

    def window_minimize(self) -> None:
        if self._window:
            try:
                self._window.minimize()
            except Exception:
                pass

    def window_maximize(self) -> None:
        if self._window:
            try:
                self._window.toggle_fullscreen()
            except Exception:
                pass

    def window_restore(self) -> None:
        if self._window:
            try:
                self._window.restore()
            except Exception:
                pass

    def window_close(self) -> None:
        """关闭按钮 → 若托盘启用则隐藏到托盘，否则真正关闭。"""
        if not self._window:
            return
        try:
            # 读取设置，判断托盘是否启用（默认启用）
            settings = self.load_settings()
            if settings.get("tray_enabled", True):
                self._window.hide()
            else:
                self._window.destroy()
        except Exception:
            pass

    def window_quit(self) -> None:
        """真正退出程序（从托盘菜单调用）。"""
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass

    def window_show(self) -> None:
        """显示窗口（从托盘恢复）。"""
        self._window_visible = True
        if self._window:
            try:
                self._window.show()
                self._window.restore()
            except Exception:
                pass

    def window_hide(self) -> None:
        """隐藏窗口到托盘。"""
        self._window_visible = False
        if self._window:
            try:
                self._window.hide()
            except Exception:
                pass

    def window_is_visible(self) -> bool:
        """窗口是否可见（基于手动追踪标记，比 _window.hidden 更可靠）。"""
        return self._window_visible

    def _toggle_window(self) -> None:
        """切换窗口显示/隐藏（供 TrayManager 调用）。"""
        if self._window_visible:
            self.window_hide()
        else:
            self.window_show()

    def _ensure_visible(self) -> None:
        """确保窗口可见并前置（托盘菜单操作前调用）。"""
        if not self._window_visible:
            self.window_show()

    def navigate_view(self, route: str) -> None:
        """让前端导航到指定路由（托盘菜单快速跳转用）。"""
        if self._window:
            try:
                self._window.evaluate_js(f"navigate('{route}')")
            except Exception:
                pass

    def _backup_notify(self, level: str, msg: str) -> None:
        """BackupManager 回调，向前端发送 toast 通知。"""
        if self._window:
            try:
                safe = msg.replace("'", "\\'")
                self._window.evaluate_js(f"toast('{safe}', '{level}')")
            except Exception:
                pass

    def window_move_by(self, dx: int, dy: int) -> None:
        """相对移动窗口（用于前端 mousemove 拖拽）。"""
        if not self._window:
            return
        try:
            x, y = self._window.x, self._window.y
            self._window.move(x + dx, y + dy)
        except Exception:
            pass

    def window_get_bounds(self) -> dict:
        """返回窗口位置和尺寸 {x, y, w, h}。"""
        if not self._window:
            return {"x": 0, "y": 0, "w": 1024, "h": 680}
        try:
            return {
                "x": self._window.x,
                "y": self._window.y,
                "w": self._window.width,
                "h": self._window.height,
            }
        except Exception:
            return {"x": 0, "y": 0, "w": 1024, "h": 680}

    def window_set_bounds(self, x: int, y: int, w: int, h: int) -> None:
        """设置窗口位置和尺寸（带最小尺寸约束）。"""
        if not self._window:
            return
        try:
            w = max(1024, int(w))
            h = max(680, int(h))
            self._window.move(int(x), int(y))
            self._window.resize(w, h)
        except Exception:
            pass

    def ensure_config_dir(self) -> dict:
        """首次运行触发：跑一次 shield plugin list 触发生成官方配置目录。"""
        if not self.runner:
            return {"error": "runner 未就绪"}
        effective = self.store.ensure_triggered(self.runner.run_cli)
        return {"ok": True, "effective_dir": effective, "config": self.store.status()}

    # ---------- 预设（连接配置） ----------

    def list_presets(self) -> list:
        return self.store.list_presets() if self.store else []

    def save_preset(self, preset: dict) -> dict:
        return self.store.save_preset(preset) if self.store else preset

    def del_preset(self, pid: str) -> bool:
        return self.store.del_preset(pid) if self.store else False

    # ---------- 隧道会话 ----------

    def build_argv(self, params: dict) -> dict:
        """根据前端表单参数构造 shield argv（仅返回参数，不执行）。"""
        return {"argv": _build_argv(params), "protocol": params.get("protocol")}

    def start_tunnel(self, params: dict) -> dict:
        """根据预设/表单参数启动隧道。"""
        if not self.runner:
            return {"error": "runner 未就绪"}
        argv = _build_argv(params)
        proto = params.get("protocol", "")
        target = params.get("target", "")
        display = params.get("display_name", "")
        # 触发探测（首次运行）
        if self.store.status().get("needs_trigger"):
            self.store.ensure_triggered(self.runner.run_cli)
        return self.runner.start_tunnel(argv, proto, target, display)

    def start_tunnel_by_argv(
        self, argv: list, protocol: str, target: str, display_name: str = ""
    ) -> dict:
        if not self.runner:
            return {"error": "runner 未就绪"}
        if self.store.status().get("needs_trigger"):
            self.store.ensure_triggered(self.runner.run_cli)
        return self.runner.start_tunnel(argv, protocol, target, display_name)

    def stop_tunnel(self, sid: str) -> bool:
        return self.runner.stop_tunnel(sid) if self.runner else False

    def remove_session(self, sid: str) -> bool:
        return self.runner.remove_session(sid) if self.runner else False

    def list_sessions(self) -> list:
        return self.runner.list_sessions() if self.runner else []

    def poll_log(self, sid: str, offset: int = 0) -> dict:
        return self.runner.poll_log(sid, offset) if self.runner else {"exists": False}

    def get_session(self, sid: str) -> dict | None:
        """获取单个会话详情（含 argv）。"""
        sess = self.runner.get_session(sid) if self.runner else None
        return sess.to_dict() if sess else None

    def restart_session(self, sid: str) -> dict:
        """重启已停止的会话（复用原 argv），成功后移除旧会话避免 UI 多出一行。"""
        if not self.runner:
            return {"error": "runner 未就绪"}
        sess = self.runner.get_session(sid)
        if not sess:
            return {"error": "会话不存在"}
        if sess.status not in ("stopped", "error"):
            return {"error": "仅允许重启已停止的会话"}
        result = self.start_tunnel_by_argv(
            sess.argv, sess.protocol, sess.target, sess.display_name,
        )
        if result.get("session_id"):
            # 新会话已创建，移除旧会话让 UI 自然替换
            self.runner.remove_session(sid)
        return result

    # ---------- 一次性命令 ----------

    def run_cli(self, argv: list, timeout: int = 60) -> dict:
        """同步执行 shield 子命令（plugin/install/stop/uninstall/clean/version 等）。"""
        if not self.runner:
            return {"code": -1, "stdout": "", "stderr": "runner 未就绪"}
        return self.runner.run_cli(argv, timeout=timeout)

    # ---------- 插件管理 ----------

    def plugin_list(self) -> dict:
        """返回结构化插件列表：已安装列表、计数、原始输出。"""
        raw = self.runner.run_cli(["plugin", "list"], timeout=30)
        stdout = raw.get("stdout") or ""
        stderr = raw.get("stderr") or ""
        full = stdout + stderr
        # 解析已安装插件名
        installed = []
        for line in full.splitlines():
            line = line.strip()
            # 跳过空行、标题、无插件提示
            if not line or "plugin" in line.lower() or "---" in line:
                continue
            # 行首可能是插件名（不含空格/特殊字符）
            parts = line.split()
            if parts and re.match(r"^[a-z][a-z0-9_-]+$", parts[0], re.I):
                installed.append(parts[0])
        return {
            "installed": installed,
            "count": len(installed),
            "stdout": stdout,
            "stderr": stderr,
            "code": raw.get("code", 0),
        }

    def plugin_add(self, name: str, from_path: str = "") -> dict:
        argv = ["plugin", "add", name]
        if from_path:
            argv += ["--from", from_path]
        raw = self.runner.run_cli(argv, timeout=180)
        # 包装返回，附带结构化信息便于前端展示
        stdout = raw.get("stdout") or ""
        stderr = raw.get("stderr") or ""
        code = raw.get("code", -1)
        success = code == 0 or any(
            kw in (stdout + stderr).lower()
            for kw in ["success", "installed", "already", "done"]
        )
        return {
            "code": code,
            "success": success,
            "stdout": stdout,
            "stderr": stderr,
            "error": stderr[:500] if not success else "",
        }

    def plugin_remove(self, name: str) -> dict:
        return self.runner.run_cli(["plugin", "remove", name], timeout=30)

    def plugin_upgrade(self, name: str = "") -> dict:
        argv = ["plugin", "upgrade"]
        if name:
            argv.append(name)
        return self.runner.run_cli(argv, timeout=180)

    # ---------- 系统服务 ----------

    def service_install(self, port: int = 8181) -> dict:
        return self.runner.run_cli(["install", "--port", str(port)], timeout=60)

    def service_uninstall(self) -> dict:
        return self.runner.run_cli(["uninstall"], timeout=60)

    def service_stop(self) -> dict:
        return self.runner.run_cli(["stop"], timeout=30)

    def service_status(self) -> dict:
        """探测 Windows 服务 ShieldCLI 的运行状态。"""
        if os.name != "nt":
            return {"installed": False, "running": False}
        try:
            r = subprocess.run(
                ["sc", "query", "ShieldCLI"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=0x08000000,
            )
            out = r.stdout + r.stderr
            installed = "SERVICE_NAME" in out
            running = "RUNNING" in out
            return {"installed": installed, "running": running, "raw": out}
        except Exception as exc:
            return {"installed": False, "running": False, "error": str(exc)}

    def start_web_ui(self, port: int = 8181) -> dict:
        """以 Popen 后台启动 shield start [port]，进程持久运行不阻塞。
        返回启动结果。"""
        if not self.runner:
            return {"error": "runner 未就绪", "code": -1}
        with self._web_ui_lock:
            # 检查是否已在运行
            if self._web_ui_process and self._web_ui_process.poll() is None:
                return {
                    "code": 0,
                    "message": f"Web UI 已在运行（端口 {port}）",
                    "already_running": True,
                }
            try:
                from core.shield_runner import CREATE_NO_WINDOW

                proc = subprocess.Popen(
                    [self.shield_exe, "start", str(port)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    cwd=os.path.dirname(self.shield_exe) or None,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                self._web_ui_process = proc
                # 读几行初始输出确认启动
                import time

                time.sleep(1.5)
                initial = ""
                while proc.stdout and proc.poll() is None:
                    try:
                        line = proc.stdout.readline()
                        if not line:
                            break
                        initial += line
                        # 读到了关键输出就停止等待
                        if any(
                            kw in line.lower()
                            for kw in [
                                "start",
                                "listen",
                                "serving",
                                "localhost",
                                "error",
                            ]
                        ):
                            break
                    except:
                        break
                return {
                    "code": 0,
                    "pid": proc.pid,
                    "message": f"Web UI 已启动（端口 {port}，PID {proc.pid}）",
                    "initial_output": initial[:2000],
                }
            except Exception as exc:
                return {"code": -1, "error": str(exc)}

    def web_ui_status(self) -> dict:
        """查询 Web UI 后台进程运行状态。"""
        with self._web_ui_lock:
            if not self._web_ui_process:
                return {"running": False, "message": "尚未启动"}
            rc = self._web_ui_process.poll()
            if rc is None:
                return {
                    "running": True,
                    "pid": self._web_ui_process.pid,
                    "message": "运行中",
                }
            else:
                self._web_ui_process = None
                return {
                    "running": False,
                    "exit_code": rc,
                    "message": f"进程已退出（退出码 {rc}）",
                }

    def stop_web_ui(self) -> dict:
        """停止 Web UI 后台进程。"""
        with self._web_ui_lock:
            if not self._web_ui_process:
                return {"ok": False, "message": "Web UI 未运行"}
            proc = self._web_ui_process
            if proc.poll() is not None:
                self._web_ui_process = None
                return {"ok": True, "message": "Web UI 已停止"}
            try:
                # 先 taskkill 进程树
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                    creationflags=0x08000000,
                )
                proc.wait(timeout=5)
                self._web_ui_process = None
                return {"ok": True, "message": "Web UI 已停止"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    def open_web_ui(self, port: int = 8181) -> bool:
        """浏览器打开 shield Web UI。"""
        url = f"http://localhost:{port}"
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    # ---------- Shield CLI 安装 ----------

    DOWNLOAD_ZIP_URL = "https://github.com/fengyily/shield-cli/releases/download/v0.3.11/shield-windows-amd64.zip"
    INSTALL_BAT_URL = (
        "https://raw.githubusercontent.com/fengyily/shield-cli/main/install.bat"
    )
    INSTALL_DIR = r"C:\Program Files\ShieldCLI"

    def download_shield_release(self) -> dict:
        """从 GitHub Release 下载 shield-windows-amd64.zip 并解压到安装目录。"""
        url = self.DOWNLOAD_ZIP_URL
        install_dir = self.INSTALL_DIR
        try:
            os.makedirs(install_dir, exist_ok=True)
            # 下载 ZIP
            zip_path = os.path.join(install_dir, "shield-windows-amd64.zip")
            progress = {"status": "downloading", "message": "正在下载 shield CLI..."}
            urllib.request.urlretrieve(url, zip_path)
            if not os.path.isfile(zip_path) or os.path.getsize(zip_path) < 1000:
                return {"ok": False, "error": "下载失败，文件过小或不存在"}
            # 解压
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(install_dir)
            os.remove(zip_path)
            # 查找解压后的 shield.exe（可能在子目录）
            exe_path = os.path.join(install_dir, "shield.exe")
            if not os.path.isfile(exe_path):
                # 搜索子目录
                for root, dirs, files in os.walk(install_dir):
                    for f in files:
                        if f.lower() == "shield.exe":
                            exe_path = os.path.join(root, f)
                            # 移动到安装目录根
                            dest = os.path.join(install_dir, "shield.exe")
                            if exe_path != dest:
                                shutil.move(exe_path, dest)
                                exe_path = dest
                            break
            installed = os.path.isfile(exe_path)
            return {
                "ok": installed,
                "error": "" if installed else "解压后未找到 shield.exe",
                "path": exe_path if installed else "",
                "install_dir": install_dir,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def install_shield_bat(self) -> dict:
        """下载 install.bat 并以管理员权限执行自动安装。"""
        url = self.INSTALL_BAT_URL
        try:
            bat_dir = os.path.join(
                os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")),
                "shield_install",
            )
            os.makedirs(bat_dir, exist_ok=True)
            bat_path = os.path.join(bat_dir, "install.bat")
            urllib.request.urlretrieve(url, bat_path)
            if not os.path.isfile(bat_path):
                return {"ok": False, "error": "install.bat 下载失败"}
            # 执行 install.bat
            proc = subprocess.run(
                ["cmd", "/c", bat_path],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=bat_dir,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            # 判断是否成功
            success = proc.returncode == 0
            # 即使退出码非零，也可能安装成功（install.bat 可能返回非零）
            if not success:
                for kw in ["success", "installed", "done", "已完成"]:
                    if kw in stdout.lower() or kw in stderr.lower():
                        success = True
                        break
            exe_found = os.path.isfile(os.path.join(self.INSTALL_DIR, "shield.exe"))
            return {
                "ok": success or exe_found,
                "code": proc.returncode,
                "stdout": stdout[:2000],
                "stderr": stderr[:2000],
                "exe_found": exe_found,
                "message": "安装完成"
                if (success or exe_found)
                else f"安装脚本执行完毕（退出码 {proc.returncode}）",
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "安装脚本执行超时（>120s）"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def check_shield_installed(self) -> dict:
        """重新检测 shield.exe 是否已安装。"""
        exe = _locate_shield()
        return {"installed": bool(exe), "path": exe or ""}

    # ---------- 凭证管理 ----------

    def clean_credentials(self) -> dict:
        return self.runner.run_cli(["clean"], timeout=30)

    # ---------- 应用设置 ----------

    def load_settings(self) -> dict:
        return self.store.load_settings() if self.store else {}

    def save_settings(self, settings: dict) -> bool:
        return self.store.save_settings(settings) if self.store else False

    # ---------- 备份恢复 ----------

    def backup_list(self, backup_dir: str = "") -> list:
        bm = BackupManager()
        return bm.list_backups(backup_dir or None)

    def backup_create(self, backup_dir: str = "") -> dict:
        bm = BackupManager()
        return bm.create_backup(backup_dir or None)

    def backup_restore(self, zip_path: str) -> dict:
        bm = BackupManager()
        return bm.restore_backup(zip_path)

    def backup_delete(self, zip_path: str) -> dict:
        bm = BackupManager()
        return bm.delete_backup(zip_path)

    def backup_get_paths(self) -> dict:
        bm = BackupManager()
        return {
            "default_dir": bm.get_default_backup_dir(),
            "shield_apps": bm.get_shield_apps_path(),
            "sources": bm.get_source_paths(),
        }

    def backup_webdav_upload(self, local_path: str, config: dict) -> dict:
        bm = BackupManager()
        return bm.webdav_upload(local_path, config)

    def backup_webdav_download(
        self, filename: str, local_dir: str, config: dict
    ) -> dict:
        bm = BackupManager()
        return bm.webdav_download(filename, local_dir, config)

    def backup_webdav_list(self, config: dict) -> list:
        bm = BackupManager()
        return bm.webdav_list(config)

    def backup_scheduler_start(
        self, interval_min: int, backup_dir: str = "", webdav_config: dict | None = None
    ) -> None:
        self._backup_mgr.scheduler_start(
            interval_min, backup_dir or None, webdav_config
        )

    def backup_scheduler_stop(self) -> None:
        self._backup_mgr.scheduler_stop()

    def backup_scheduler_status(self) -> dict:
        return self._backup_mgr.scheduler_status()

    # ---------- 文件对话框 ----------

    def pick_private_key(self) -> str:
        """pywebview 文件对话框，选私钥文件。"""
        if not self._window:
            return ""
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "All files (*.*)",
                    "Private key files (*.pem;*.key;*.id_rsa)",
                ),
            )
            if isinstance(result, list) and result:
                return result[0]
            if isinstance(result, str):
                return result
            return ""
        except Exception:
            return ""

    def echo(self, text: str = "") -> str:
        """桥接连通性自检。"""
        return f"pong: {text}"


# ---------- 工具函数 ----------


def _locate_shield() -> str:
    """定位 shield.exe：PATH → Program Files → 常见安装位置。"""
    exe = shutil.which("shield") or shutil.which("shield.exe")
    if exe:
        return exe
    candidates = [
        r"C:\Program Files\ShieldCLI\shield.exe",
        r"C:\Program Files (x86)\ShieldCLI\shield.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ShieldCLI", "shield.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), "shield.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""


def _build_argv(params: dict) -> list:
    """把前端表单参数转成 shield argv。

    params:
      protocol: ssh|rdp|vnc|http|https|telnet|tcp|udp|<plugin>
      target: "ip:port" | "port" | "ip" | ""
      username/auth_pass/private_key/passphrase/enable_sftp (SSH/RDP/VNC)
      db_name/db_user/db_pass/readonly (插件)
      display_name/site_name/visable/invisible/tunnel_port/server
    """
    proto = params.get("protocol", "ssh")
    argv: list[str] = [proto]

    target = (params.get("target") or "").strip()
    if target:
        # 如果只输入了纯数字端口，补上 127.0.0.1:
        if re.match(r"^\d+$", target):
            target = f"127.0.0.1:{target}"
        argv.append(target)
    elif proto in PROTOCOLS and PROTOCOLS[proto]["port"]:
        # 省略 target → shield 默认 127.0.0.1:标准端口，无需传参
        pass

    # 认证参数（SSH/RDP/VNC）
    if params.get("username"):
        argv += ["--username", str(params["username"])]
    if params.get("auth_pass"):
        argv += ["--auth-pass", str(params["auth_pass"])]
    if params.get("private_key"):
        argv += ["--private-key", str(params["private_key"])]
    if params.get("passphrase"):
        argv += ["--passphrase", str(params["passphrase"])]
    if params.get("enable_sftp"):
        argv.append("--enable-sftp")

    # 数据库参数（插件协议）
    if proto in PLUGIN_PROTOCOLS or params.get("db_name"):
        if params.get("db_name"):
            argv += ["--db-name", str(params["db_name"])]
        if params.get("db_user"):
            argv += ["--db-user", str(params["db_user"])]
        if params.get("db_pass"):
            argv += ["--db-pass", str(params["db_pass"])]
        if params.get("readonly"):
            argv.append("--readonly")

    # 高级参数
    if params.get("display_name"):
        argv += ["--display-name", str(params["display_name"])]
    if params.get("site_name"):
        argv += ["--site-name", str(params["site_name"])]
    if params.get("visable"):
        argv += ["--visable", str(params["visable"])]
    if params.get("invisible"):
        argv.append("--invisible")
    if params.get("tunnel_port"):
        try:
            argv += ["--tunnel-port", str(int(params["tunnel_port"]))]
        except (TypeError, ValueError):
            pass
    if params.get("server"):
        argv += ["--server", str(params["server"])]
    if params.get("verbose"):
        argv.append("--verbose")

    return argv


def _compare_versions(v1: str, v2: str) -> int:
    """比较两个语义化版本号。返回 1 (v1>v2), -1 (v1<v2), 0 (相等)。"""

    def parse(v: str):
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(re.search(r"\d+", p).group()))
            except (AttributeError, ValueError):
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return parts[:3]

    a, b = parse(v1), parse(v2)
    for i in range(3):
        if a[i] > b[i]:
            return 1
        if a[i] < b[i]:
            return -1
    return 0
