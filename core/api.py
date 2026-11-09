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
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from typing import Any, Optional

import json
from datetime import datetime
from core import net_diag, process_guard, updater
from core.backup import BackupManager
from core.config_store import ConfigStore
from core.shield_runner import ShieldRunner
from core.webui_client import DEFAULT_PORT as WEBUI_DEFAULT_PORT
from core.webui_client import WebUIClient


# 本 GUI 版本号（用于更新检测）
# 内置兜底版本号（pyproject.toml 不可读时使用，CI 构建时自动同步）
_FALLBACK_VERSION = "1.0.0"

# =============================================================================
# 会话容量上限（硬约束）
#   MAX_SESSIONS —— 「活动会话」列表最多保留的条目数
#   MAX_RUNNING  —— 同时处于 running/starting 的隧道数
# =============================================================================
MAX_SESSIONS = 10
MAX_RUNNING = 3
_ACTIVE_STATUS = ("running", "starting")


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
        self.runner = (
            ShieldRunner(self.shield_exe, on_error=self._on_session_error)
            if self.shield_exe else None
        )
        self.store = ConfigStore(self.shield_exe) if self.shield_exe else None
        self._window = None
        # 启动前网络预检缓存 (timestamp, server, proxy, result)
        self._preflight_cache: Optional[tuple] = None
        # Web UI 后台进程管理（shield start 长驻进程）
        self._web_ui_process: Optional[subprocess.Popen] = None
        self._web_ui_lock = threading.Lock()
        # Web 面板 API 客户端：让 Web 里添加的应用显示在「活动会话」
        self._web_port = WEBUI_DEFAULT_PORT
        self._web_client = WebUIClient(self._web_port)
        self._window_visible = True  # 手动追踪，比 _window.hidden 更可靠
        self._backup_mgr = BackupManager(on_notify=self._backup_notify)
        # 更新状态（前端进度条读取）
        self._updating = False
        self._update_state: dict = {"stage": "idle", "percent": 0, "message": ""}
        self._load_web_port()

    def attach_window(self, window) -> None:
        self._window = window

    # ---------- Web 面板（shield start）联动 ----------

    def _load_web_port(self) -> None:
        """从设置里读取 Web UI 端口，保持客户端指向正确端口。"""
        port = WEBUI_DEFAULT_PORT
        try:
            if self.store:
                saved = self.store.load_settings().get("web_ui_port")
                if saved:
                    port = int(saved)
        except (ValueError, TypeError):
            port = WEBUI_DEFAULT_PORT
        self._web_port = port
        if getattr(self, "_web_client", None) is None or self._web_client.port != port:
            self._web_client = WebUIClient(port)

    def _web_sessions(self) -> list:
        """官方 Web 面板里的应用映射成的会话（Web UI 未启动时返回空）。"""
        try:
            return self._web_client.sessions()
        except Exception:  # noqa: BLE001
            return []

    def web_ui_info(self) -> dict:
        """Web 面板探测信息：是否在线、版本、应用数、已连接数。"""
        client = self._web_client
        online = client.is_available(force=True)
        apps = client.apps(force=True) if online else []
        connected = sum(
            1
            for a in apps
            if str((a.get("conn_status") or {}).get("status") or "").lower()
            in ("connected", "connecting")
        )
        managed = bool(
            self._web_ui_process and self._web_ui_process.poll() is None
        )
        return {
            "port": self._web_port,
            "url": f"http://localhost:{self._web_port}/",
            "online": online,
            "version": client.version() if online else "",
            "apps": len(apps),
            "connected": connected,
            "managed_by_gui": managed,
        }

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

    # ---------- 更新检测与安装 ----------

    def _update_mirrors(self) -> list:
        """读取用户配置的镜像前缀（默认 ghproxy.net / v4.gh-proxy.org）。"""
        raw = None
        try:
            if self.store:
                raw = self.store.load_settings().get("update_mirrors")
        except Exception:  # noqa: BLE001
            raw = None
        return updater.normalize_mirrors(raw)

    def _shield_version(self) -> str:
        """当前 shield.exe 的版本号（解析 --version 输出）。"""
        if not self.runner:
            return ""
        try:
            ver_res = self.runner.run_cli(["--version"], timeout=8)
        except Exception:  # noqa: BLE001
            return ""
        for line in (ver_res.get("stdout", "") + ver_res.get("stderr", "")).splitlines():
            m = re.search(r"(\d+\.\d+\.\d+)", line)
            if m:
                return m.group(1)
        return ""

    def check_updates(self) -> dict:
        """检测 GUI / CLI 新版本（不打开 GitHub 页面，只取直链与镜像）。

        元信息获取走 updater.fetch_release 的多通道降级：
        API 直连 → 镜像透传 API → releases/latest 重定向。
        下载链接同时给出「GitHub 直链 + 镜像加速链接」候选。
        """
        mirrors = self._update_mirrors()
        result = {
            "gui": {
                "has_update": False,
                "latest_version": "",
                "current_version": GUI_VERSION,
                "download_url": "",
                "download_urls": [],
                "asset": "",
                "release_url": "",
                "via": "",
            },
            "shield": {
                "has_update": False,
                "latest_version": "",
                "current_version": "",
                "download_url": "",
                "download_urls": [],
                "asset": "",
                "release_url": "",
                "via": "",
            },
            "mirrors": mirrors,
            "errors": [],
        }

        # ---- GUI 自身（shield-gui）----
        try:
            rel = updater.fetch_release(updater.GUI_REPO, mirrors)
            latest = rel.get("tag", "")
            result["gui"]["latest_version"] = latest
            result["gui"]["via"] = rel.get("via", "")
            result["gui"]["release_url"] = rel.get("html_url", "")
            if latest and _compare_versions(latest, GUI_VERSION) > 0:
                asset = updater.pick_asset(rel.get("assets") or [], "gui") or "ShieldGUI.exe"
                urls = updater.asset_candidates(
                    updater.GUI_REPO, asset, rel.get("tag_raw") or "", mirrors
                )
                result["gui"].update(
                    {
                        "has_update": True,
                        "asset": asset,
                        "download_url": urls[0],
                        "download_urls": urls,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"GUI：{str(exc)[:200]}")

        # ---- Shield CLI ----
        try:
            current_shield = self._shield_version()
            result["shield"]["current_version"] = current_shield
            rel = updater.fetch_release(updater.CLI_REPO, mirrors)
            latest = rel.get("tag", "")
            result["shield"]["latest_version"] = latest
            result["shield"]["via"] = rel.get("via", "")
            result["shield"]["release_url"] = rel.get("html_url", "")
            if (
                current_shield
                and latest
                and _compare_versions(latest, current_shield) > 0
            ):
                asset = updater.pick_asset(
                    rel.get("assets") or [], "cli"
                ) or "shield-windows-amd64.zip"
                urls = updater.asset_candidates(
                    updater.CLI_REPO, asset, rel.get("tag_raw") or "", mirrors
                )
                result["shield"].update(
                    {
                        "has_update": True,
                        "asset": asset,
                        "download_url": urls[0],
                        "download_urls": urls,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"CLI：{str(exc)[:200]}")

        return result

    # ---- 更新配置 ----

    def get_update_config(self) -> dict:
        """返回更新通道配置（镜像列表 + 当前版本）。"""
        return {
            "mirrors": self._update_mirrors(),
            "default_mirrors": list(updater.DEFAULT_MIRRORS),
            "gui_version": GUI_VERSION,
            "shield_version": self._shield_version(),
            "frozen": updater.is_frozen(),
            "executable": updater.current_exe(),
            "updating": self._updating,
        }

    def save_update_mirrors(self, mirrors) -> dict:
        """保存镜像前缀列表（空则恢复默认）。"""
        normalized = updater.normalize_mirrors(mirrors)
        settings = self.load_settings() if self.store else {}
        settings["update_mirrors"] = normalized
        ok = self.save_settings(settings) if self.store else False
        return {"ok": ok, "mirrors": normalized}

    # ---- 进度推送 ----

    def _push_update(
        self, stage: str, percent: int, message: str, extra: dict | None = None
    ) -> None:
        """把更新进度推给前端进度条（UpdateUI.onProgress）。"""
        payload = {
            "stage": stage,
            "percent": max(0, min(100, int(percent))),
            "message": message,
        }
        if extra:
            payload.update(extra)
        self._update_state = payload
        if self._window:
            try:
                js = (
                    "window.UpdateUI && window.UpdateUI.onProgress("
                    + json.dumps(payload, ensure_ascii=False)
                    + ");"
                )
                self._window.evaluate_js(js)
            except Exception:  # noqa: BLE001
                pass

    def update_state(self) -> dict:
        return dict(self._update_state, updating=self._updating)

    # ---- 发起更新 ----

    def install_update(self, target: str = "gui") -> dict:
        """开始下载并替换更新（异步，进度通过进度条推送）。

        target: ``gui`` 更新本程序（下载 exe 后自我替换并重启）
                ``shield`` 更新 shield.exe（下载 zip 解压后替换）
        """
        target = (target or "gui").lower()
        if target not in ("gui", "shield"):
            return {"started": False, "error": f"未知更新目标：{target}"}
        if self._updating:
            return {"started": False, "error": "已有更新任务在进行中"}
        if target == "shield" and not self.shield_exe:
            return {"started": False, "error": "未找到 shield.exe，请先安装 Shield CLI"}

        self._updating = True
        self._push_update("prepare", 0, "正在准备更新…")
        threading.Thread(
            target=self._do_update, args=(target,), daemon=True
        ).start()
        return {"started": True, "target": target, "mirrors": self._update_mirrors()}

    def _do_update(self, target: str) -> None:
        mirrors = self._update_mirrors()
        try:
            if target == "shield":
                self._update_cli(mirrors)
            else:
                self._update_gui(mirrors)
        except Exception as exc:  # noqa: BLE001
            self._push_update("error", 0, f"更新失败：{exc}")
        finally:
            self._updating = False

    def _update_gui(self, mirrors: list) -> None:
        self._push_update("check", 2, "正在查询最新版本（GitHub / 镜像）…")
        rel = updater.fetch_release(updater.GUI_REPO, mirrors)
        latest = rel.get("tag", "")
        if latest and _compare_versions(latest, GUI_VERSION) <= 0:
            self._push_update(
                "up_to_date", 100, f"已是最新版本 v{GUI_VERSION}"
            )
            return

        asset = updater.pick_asset(rel.get("assets") or [], "gui") or "ShieldGUI.exe"
        urls = updater.asset_candidates(
            updater.GUI_REPO, asset, rel.get("tag_raw") or "", mirrors
        )
        workdir = os.path.join(tempfile.gettempdir(), "shield-gui-update")
        os.makedirs(workdir, exist_ok=True)
        dest = os.path.join(workdir, asset)
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass

        self._push_update("download", 4, f"开始下载 v{latest}（{asset}）…")
        client = self

        def _prog(got: int, total: int) -> None:
            if total:
                pct = 4 + int(got * 86 / total)
                text = (
                    f"下载 v{latest}：{got / 1048576:.1f}/"
                    f"{total / 1048576:.1f} MB"
                )
            else:
                pct, text = 40, f"下载 v{latest}：{got / 1048576:.1f} MB"
            client._push_update("download", min(pct, 90), text)

        res = updater.download(urls, dest, progress=_prog)
        if not res.get("ok"):
            detail = "；".join(str(t) for t in (res.get("tried") or [])[-3:])
            self._push_update("error", 0, "下载失败，请检查网络或更换镜像：" + detail)
            return

        exe_path = dest
        if asset.lower().endswith(".zip"):
            self._push_update("extract", 92, "正在解压安装包…")
            exe_path = (
                updater.extract_exe(dest, workdir, "ShieldGUI.exe")
                or updater.extract_exe(dest, workdir, "shield-gui.exe")
                or ""
            )
            if not exe_path:
                self._push_update("error", 0, "安装包内未找到 ShieldGUI.exe")
                return

        # 源码运行（python main.py）：无法替换自身，只把新版放到临时目录
        if not updater.is_frozen():
            self._push_update(
                "done",
                100,
                f"v{latest} 已下载到 {exe_path}；当前为源码运行模式，请手动替换并重启",
                {"manual": True, "path": exe_path, "version": latest},
            )
            return

        self._push_update("replace", 96, "正在替换程序文件…")
        rep = updater.schedule_self_replace(exe_path, updater.current_exe())
        if not rep.get("ok"):
            self._push_update(
                "error", 0, f"替换失败：{rep.get('error', '未知错误')}"
            )
            return
        self._push_update(
            "restart",
            100,
            f"更新完成，正在重启到 v{latest}…",
            {"version": latest},
        )
        time.sleep(1.2)
        self.window_quit()

    def _update_cli(self, mirrors: list) -> None:
        if not self.runner:
            self._push_update("error", 0, "runner 未就绪")
            return
        self._push_update("check", 2, "正在查询 Shield CLI 最新版本…")
        latest = ""
        rel = updater.fetch_release(updater.CLI_REPO, mirrors)
        latest = rel.get("tag", "")
        current = self._shield_version()
        if current and latest and _compare_versions(latest, current) <= 0:
            self._push_update("up_to_date", 100, f"Shield CLI 已是最新 v{current}")
            return

        asset = updater.pick_asset(
            rel.get("assets") or [], "cli"
        ) or "shield-windows-amd64.zip"
        urls = updater.asset_candidates(
            updater.CLI_REPO, asset, rel.get("tag_raw") or "", mirrors
        )
        workdir = os.path.join(tempfile.gettempdir(), "shield-cli-update")
        os.makedirs(workdir, exist_ok=True)
        dest = os.path.join(workdir, asset)
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass

        self._push_update("download", 4, f"开始下载 CLI v{latest}（{asset}）…")
        client = self

        def _prog(got: int, total: int) -> None:
            if total:
                pct = 4 + int(got * 76 / total)
                text = (
                    f"下载 CLI v{latest}：{got / 1048576:.1f}/"
                    f"{total / 1048576:.1f} MB"
                )
            else:
                pct, text = 40, f"下载 CLI v{latest}：{got / 1048576:.1f} MB"
            client._push_update("download", min(pct, 80), text)

        res = updater.download(urls, dest, progress=_prog)
        if not res.get("ok"):
            detail = "；".join(str(t) for t in (res.get("tried") or [])[-3:])
            self._push_update("error", 0, "下载失败：" + detail)
            return

        # ---------- 先结束全部 shield.exe 进程，再替换文件 ----------
        # 只停 GUI 自己拉起的会话是不够的：外部手动启动的 Web 面板、
        # 系统托盘、命令行实例和 Windows 服务同样会锁住 shield.exe，
        # 要么让 os.replace 失败，要么出现「文件换了、内存里还跑旧版」。
        snap = self._snapshot_running_state()
        target = self.shield_exe or os.path.join(
            r"C:\Program Files\ShieldCLI", "shield.exe"
        )
        self._push_update(
            "stop", 82,
            "正在结束所有 Shield CLI 进程（隧道 / Web 面板 / 托盘 / 服务）…",
        )
        guard = self._stop_everything(target)
        snap["web_ports"] = list(guard.get("ports") or [])
        snap["service_was_running"] = bool(guard.get("service", {}).get("was_running"))
        if not snap["web_ui_online"] and snap["web_ports"]:
            snap["web_ui_online"] = True  # 进程枚举里发现过 `shield start <port>`
        killed_n = len(guard.get("killed") or [])
        self._push_update(
            "stop", 84,
            f"已结束 {killed_n} 个 shield.exe 进程，正在确认文件解除占用…",
        )
        blockers = guard.get("survivors") or []
        if blockers or not guard.get("file_writable", True):
            detail = "、".join(process_guard.describe(p) for p in blockers[:3])
            self._push_update(
                "error", 0,
                f"无法结束占用 shield.exe 的进程（{detail or '文件仍被占用'}）；"
                "请手动结束这些进程或重启后再试，原文件未被改动",
            )
            self._restore_after_update(snap)
            return

        self._push_update("extract", 88, "正在解压并替换 shield.exe…")
        extract_dir = os.path.join(workdir, "extract")
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        try:
            found = updater.extract_exe(dest, extract_dir, "shield.exe")
        except Exception as exc:  # noqa: BLE001
            self._push_update("error", 0, f"解压失败：{exc}")
            self._restore_after_update(snap)
            return
        if not found:
            self._push_update("error", 0, "安装包内未找到 shield.exe")
            self._restore_after_update(snap)
            return

        backup = target + ".bak"
        rep = updater.replace_file_with_retry(found, target)
        if not rep.get("ok"):
            rolled = self._rollback_cli(backup, target)
            self._push_update(
                "error", 0,
                f"替换 shield.exe 失败：{rep.get('error', '未知错误')}"
                + ("（已回滚到旧版本）" if rolled else ""),
            )
            self._restore_after_update(snap)
            return

        # 刷新内部路径缓存（保留被替换的那个路径，避免 PATH 里另有旧副本导致版本判断失真）
        new_exe = target if os.path.isfile(target) else (_locate_shield() or target)
        self.shield_exe = new_exe
        if self.runner:
            self.runner.shield_exe = new_exe
        if self.store:
            self.store.shield_exe = new_exe

        new_ver = self._shield_version()
        if not new_ver or (latest and _compare_versions(new_ver, latest) < 0):
            rolled = self._rollback_cli(backup, target)
            self._push_update(
                "error", 0,
                "新版本 shield.exe 校验未通过（无法运行或版本未提升）"
                + ("，已回滚到旧版本" if rolled else "，请检查 shield.exe.bak"),
            )
            self._restore_after_update(snap)
            return

        self._push_update(
            "restore", 96, "新版本已就位，正在恢复更新前的会话与 Web 面板…"
        )
        restored = self._restore_after_update(snap)
        parts = [
            f"Shield CLI 已更新到 v{new_ver}（旧版备份 shield.exe.bak）",
            f"结束进程 {killed_n} 个",
        ]
        if restored.get("web_ui"):
            parts.append("Web 面板已重启")
        if restored.get("service"):
            parts.append("系统服务已恢复")
        resumed = (restored.get("local") or 0) + (restored.get("web_connections") or 0)
        if resumed:
            parts.append(f"恢复会话 {resumed} 个")
        if restored.get("skipped"):
            parts.append(f"{restored['skipped']} 个因并发上限未自动恢复")
        self._push_update(
            "done", 100, "；".join(parts),
            {"version": new_ver, "killed": killed_n, "restore": restored},
        )

    # ---------- 更新时的进程清理与恢复 ----------

    def _snapshot_running_state(self) -> dict:
        """记录更新前正在跑的东西，替换完成后把它们拉回来。"""
        snap = {
            "local": [], "local_sids": [], "web_connected": [],
            "web_ui_online": False, "web_ports": [], "service_was_running": False,
        }
        try:
            for sess in (self.runner.list_sessions() if self.runner else []):
                if sess.get("status") not in _ACTIVE_STATUS:
                    continue
                snap["local_sids"].append(sess["session_id"])
                snap["local"].append(
                    {
                        "argv": list(sess.get("argv") or []),
                        "protocol": sess.get("protocol") or "",
                        "target": sess.get("target") or "",
                        "display_name": sess.get("display_name") or "",
                    }
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._web_client.is_available(force=True):
                snap["web_ui_online"] = True
                for app in self._web_client.apps(force=True):
                    state = str(
                        (app.get("conn_status") or {}).get("status") or ""
                    ).lower()
                    app_id = app.get("id") or app.get("app_id")
                    if app_id and state in ("connected", "connecting"):
                        snap["web_connected"].append(str(app_id))
        except Exception:  # noqa: BLE001
            pass
        return snap

    def _stop_everything(self, target: str = "") -> dict:
        """结束全部 shield.exe 进程，释放目标文件占用。

        顺序：GUI 管理的会话优雅退出（保住状态/日志）→ 停 GUI 的 Web UI →
        强制结束所有残留 shield.exe（含外部面板、托盘、服务）。
        """
        try:
            if self.runner:
                for sess in self.runner.list_sessions():
                    if sess.get("status") in _ACTIVE_STATUS:
                        self.runner.stop_tunnel(sess["session_id"])
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._web_ui_process and self._web_ui_process.poll() is None:
                self.stop_web_ui()
        except Exception:  # noqa: BLE001
            pass
        result = process_guard.terminate_all(
            target or self.shield_exe or "", timeout=8.0
        )
        try:
            with self._web_ui_lock:
                self._web_ui_process = None  # 已由 taskkill 结束，允许后面重启
            self._web_client.invalidate()
        except Exception:  # noqa: BLE001
            pass
        return result

    def _rollback_cli(self, backup: str, target: str) -> bool:
        """替换失败或新版本校验不过时，用 .bak 还原 shield.exe。"""
        if not os.path.isfile(backup):
            return False
        try:
            process_guard.terminate_all(target, timeout=4.0)
            shutil.copy2(backup, target)
            return True
        except OSError:
            return False

    def _restore_after_update(self, snap: dict) -> dict:
        """把更新前的 Web 面板、面板连接、隧道会话恢复到新版本上。

        遵守 MAX_RUNNING 并发上限；超出部分不自动拉起，交由用户手动启动。
        外部手动启动的进程不会被克隆，只按原端口重启一份 Web 面板。
        """
        out = {
            "web_ui": False, "service": False,
            "local": 0, "web_connections": 0, "skipped": 0,
        }
        # 旧会话已被杀掉，清掉记录以免占着 10 个名额
        for sid in snap.get("local_sids") or []:
            try:
                if self.runner:
                    self.runner.remove_session(sid)
            except Exception:  # noqa: BLE001
                pass

        running = 0
        # 服务优先：服务自己会拉起 Web 面板，避免和 GUI 再起一份抢端口
        if snap.get("service_was_running"):
            out["service"] = process_guard.start_cli_service()
            out["web_ui"] = out["service"]
        elif snap.get("web_ui_online"):
            ports = snap.get("web_ports") or [self._web_port]
            port = ports[0] or self._web_port
            try:
                if self._web_client.is_available(force=True):
                    # 结束阶段没杀干净、面板仍在线：不要重复启动抢端口
                    out["web_ui"] = True
                else:
                    res = self.start_web_ui(port)
                    out["web_ui"] = bool(
                        res.get("code") == 0 or res.get("already_running")
                    )
            except Exception:  # noqa: BLE001
                pass

        # 等面板就绪（start_web_ui 内部已等 1.5s，这里再做兜底轮询）
        for _ in range(16):
            try:
                if self._web_client.is_available(force=True):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)

        for app_id in snap.get("web_connected") or []:
            if running >= MAX_RUNNING:
                out["skipped"] += 1
                continue
            try:
                if self._web_client.connect(app_id).get("ok"):
                    out["web_connections"] += 1
                    running += 1
            except Exception:  # noqa: BLE001
                pass

        for item in snap.get("local") or []:
            if running >= MAX_RUNNING:
                out["skipped"] += 1
                continue
            if not item.get("argv"):
                continue
            try:
                res = self.start_tunnel_by_argv(
                    item["argv"], item["protocol"], item["target"],
                    item["display_name"], _skip_limit=True,
                )
                if not res.get("error"):
                    out["local"] += 1
                    running += 1
            except Exception:  # noqa: BLE001
                pass
        try:
            self._web_client.invalidate()
        except Exception:  # noqa: BLE001
            pass
        return out

    def get_gui_version(self) -> str:
        return GUI_VERSION

    # ---------- 窗口控制（frameless 模式） ----------

    def window_minimize(self) -> None:
        if self._window:
            try:
                self._window.minimize()
            except Exception:
                pass

    # 最大化/还原已移除：frameless 窗口只保留「最小化 + 关闭到托盘」，
    # 双击标题栏由前端映射到 window_minimize。
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

    # ---------- 网络与启动配置 ----------

    def _network_config(self) -> dict:
        """读取启动相关的设置（带默认值）。"""
        s = self.load_settings() if self.store else {}
        try:
            auto_retry = max(0, min(3, int(s.get("auto_retry", 1))))
        except (TypeError, ValueError):
            auto_retry = 1
        return {
            "server": (s.get("server") or "").strip(),
            "proxy": (s.get("proxy") or "").strip(),
            "preflight": s.get("preflight") is not False,
            "auto_retry": auto_retry,
        }

    def _merge_defaults(self, params: dict) -> dict:
        """把「应用配置」里保存的默认值合并进启动参数。

        修复：设置页保存的 server / visable / tunnel_port 原先只落盘、
        从未传给 shield CLI；表单里显式填写的值仍然优先。
        """
        p = dict(params or {})
        if not self.store:
            return p
        s = self.load_settings()
        for key in ("server", "visable", "tunnel_port", "invisible", "verbose"):
            if not p.get(key) and s.get(key):
                p[key] = s[key]
        return p

    @staticmethod
    def _server_of(argv: list, params: dict | None = None) -> str:
        """取本次连接实际使用的服务器地址（用于诊断展示）。"""
        if params and params.get("server"):
            return net_diag.normalize_server(params["server"])
        for i, a in enumerate(argv or []):
            if a in ("--server", "-H") and i + 1 < len(argv):
                return net_diag.normalize_server(argv[i + 1])
        return net_diag.DEFAULT_SERVER

    @staticmethod
    def _child_env(proxy: str = "") -> dict:
        """构造 CLI 子进程环境；显式代理会覆盖系统环境变量。"""
        env = os.environ.copy()
        env.update(net_diag.proxy_env(proxy))
        return env

    def _preflight(self, params: dict, force: bool = False) -> dict:
        """启动前探测控制台。成功结果缓存 5 分钟、失败结果缓存 20 秒。"""
        cfg = self._network_config()
        if not cfg["preflight"] or force:
            return {"ok": True, "skipped": True, "message": "已跳过预检"}
        server = net_diag.normalize_server(params.get("server") or cfg["server"])
        proxy = cfg["proxy"]
        now = time.time()
        cache = self._preflight_cache
        if cache and cache[1] == server and cache[2] == proxy:
            ttl = 300 if cache[3].get("ok") else 20
            if now - cache[0] < ttl:
                return {**cache[3], "cached": True}
        res = net_diag.probe(server, proxy, timeout=2.5)
        self._preflight_cache = (now, server, proxy, res)
        return res

    def probe_server(self, server: str = "", proxy: str = "") -> dict:
        """手动测试控制台连通性（不走缓存，供「应用配置」页调用）。"""
        cfg = self._network_config()
        srv = net_diag.normalize_server(server or cfg["server"])
        px = (proxy or cfg["proxy"]).strip()
        res = net_diag.probe(srv, px, timeout=6.0)
        self._preflight_cache = (time.time(), srv, px, res)
        return res

    def _toast(self, msg: str, level: str = "info") -> None:
        """后端主动推送 toast（会话启动失败 / 自动重试提示）。"""
        if not self._window:
            return
        try:
            safe = (
                msg.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
            )
            self._window.evaluate_js(f"toast('{safe}', '{level}')")
        except Exception:  # noqa: BLE001
            pass

    def _on_session_error(self, sid: str, diag: dict) -> None:
        """CLI 启动失败回调：提示用户 + 按配置自动重试。"""
        title = diag.get("title") or "隧道启动失败"
        advice = (diag.get("advice") or ["请查看会话日志"])[0]
        self._toast(f"{title}：{advice}", "error")
        cfg = self._network_config()
        sess = self.runner.get_session(sid) if self.runner else None
        if not sess:
            return
        if not cfg["auto_retry"] or not diag.get("retryable"):
            return
        if sess.retry_count >= cfg["auto_retry"]:
            self._toast(
                f"已自动重试 {sess.retry_count} 次仍失败，请检查网络后手动重试",
                "warning",
            )
            return
        delay = 2.0 + sess.retry_count * 2.0
        self._toast(
            f"{delay:.0f} 秒后自动重试（第 {sess.retry_count + 1}/{cfg['auto_retry']} 次）",
            "info",
        )
        timer = threading.Timer(delay, self._auto_retry, args=(sid,))
        timer.daemon = True  # 不阻塞 GUI 退出
        timer.start()

    def _auto_retry(self, sid: str) -> None:
        try:
            if not self.runner or not self.runner.get_session(sid):
                return  # 用户已手动移除或已重试
            res = self.retry_session(sid)
            if res.get("error"):
                self._toast("自动重试未启动：" + res["error"], "warning")
        except Exception:  # noqa: BLE001
            pass

    # ---------- 隧道会话 ----------

    def build_argv(self, params: dict) -> dict:
        """根据前端表单参数构造 shield argv（仅返回参数，不执行）。"""
        return {"argv": _build_argv(params), "protocol": params.get("protocol")}

    def start_tunnel(self, params: dict, force: bool = False) -> dict:
        """启动隧道：合并默认设置 → 网络预检 → spawn（带代理环境）。

        预检失败时返回 ``need_confirm``，由前端询问「是否仍要启动」；
        用户确认后以 ``force=True`` 再次调用，不会硬拦。
        """
        if not self.runner:
            return {"error": "runner 未就绪"}
        guard = self._check_limits()
        if guard:
            return {"error": guard, "limit": self.session_limits()}
        p = self._merge_defaults(params)
        cfg = self._network_config()
        pre = self._preflight(p, force=force)
        if not pre.get("ok") and not force:
            return {
                "error": pre.get("message") or "控制台不可达，启动可能失败",
                "diagnosis": {
                    "title": pre.get("stage_label", "网络检测") + "失败",
                    "reason": pre.get("message", ""),
                    "advice": pre.get("advice", []),
                    "detail": pre.get("detail", ""),
                },
                "preflight": pre,
                "need_confirm": True,
            }
        argv = _build_argv(p)
        proto = p.get("protocol", "")
        target = p.get("target", "")
        display = p.get("display_name", "")
        # 触发探测（首次运行）
        if self.store.status().get("needs_trigger"):
            self.store.ensure_triggered(self.runner.run_cli)
        res = self.runner.start_tunnel(
            argv, proto, target, display,
            env=self._child_env(cfg["proxy"]),
            server=self._server_of(argv, p),
        )
        res["preflight"] = pre
        return res

    def start_tunnel_by_argv(
        self, argv: list, protocol: str, target: str, display_name: str = "",
        _skip_limit: bool = False,
    ) -> dict:
        if not self.runner:
            return {"error": "runner 未就绪"}
        if not _skip_limit:
            guard = self._check_limits()
            if guard:
                return {"error": guard, "limit": self.session_limits()}
        if self.store.status().get("needs_trigger"):
            self.store.ensure_triggered(self.runner.run_cli)
        cfg = self._network_config()
        return self.runner.start_tunnel(
            argv, protocol, target, display_name,
            env=self._child_env(cfg["proxy"]),
            server=self._server_of(argv),
        )

    def retry_session(self, sid: str) -> dict:
        """用原参数重试失败/停止的会话，返回新会话（旧条目会被替换）。"""
        if sid.startswith("web:"):
            return self.restart_session(sid)
        if not self.runner:
            return {"error": "runner 未就绪"}
        sess = self.runner.get_session(sid)
        if not sess:
            return {"error": "会话不存在或已被移除"}
        if sess.process and sess.process.poll() is None:
            self.runner.stop_tunnel(sid)
        guard = self._check_limits(exclude_sids=(sid,))
        if guard:
            return {"error": guard, "limit": self.session_limits()}
        prev_log = sess.log_buffer[-4000:]
        cfg = self._network_config()
        res = self.runner.start_tunnel(
            sess.argv, sess.protocol, sess.target, sess.display_name,
            env=self._child_env(cfg["proxy"]),
            server=sess.server or self._server_of(sess.argv),
            retry_count=sess.retry_count + 1,
        )
        if res.get("error"):
            return res
        if prev_log:
            self.runner.seed_log(
                res["session_id"],
                f"[上一次尝试的日志]\n{prev_log}\n\n[本次重试]\n",
            )
        self.runner.remove_session(sid)
        return res

    # ---------- 容量上限 ----------

    def _check_limits(self, exclude_sids=()) -> str:
        """启动前校验：并发数不超过 MAX_RUNNING，会话总数不超过 MAX_SESSIONS。

        返回空串表示可以启动，否则返回面向用户的中文原因。
        """
        sessions = [
            s for s in self.list_sessions()
            if s.get("session_id") not in set(exclude_sids)
        ]
        running = [s for s in sessions if s.get("status") in _ACTIVE_STATUS]
        if len(running) >= MAX_RUNNING:
            return (
                f"同时连接数已达上限（最多 {MAX_RUNNING} 个），"
                "请先停止其他隧道（含 Web 面板里的连接）"
            )
        if len(sessions) >= MAX_SESSIONS:
            return (
                f"活动会话已达上限（最多 {MAX_SESSIONS} 个），请先移除不用的会话"
            )
        return ""

    def session_limits(self) -> dict:
        """当前容量占用情况，供前端展示 x/3、y/10 并禁用启动按钮。"""
        sessions = self.list_sessions()
        running = sum(1 for s in sessions if s.get("status") in _ACTIVE_STATUS)
        web = [s for s in sessions if s.get("source") == "web"]
        client = self._web_client
        online = client.is_available()
        return {
            "max_sessions": MAX_SESSIONS,
            "max_running": MAX_RUNNING,
            "sessions": len(sessions),
            "running": running,
            "gui_sessions": len(sessions) - len(web),
            "web_sessions": len(web),
            "remaining_sessions": max(0, MAX_SESSIONS - len(sessions)),
            "remaining_running": max(0, MAX_RUNNING - running),
            "can_start": len(sessions) < MAX_SESSIONS and running < MAX_RUNNING,
            "web_ui_online": online,
            "web_ui_port": self._web_port,
            "web_ui_url": f"http://localhost:{self._web_port}/",
        }

    # ---------- 会话操作（本地 + Web 面板） ----------

    def stop_tunnel(self, sid: str) -> bool:
        """停止会话：Web 会话走 /api/disconnect，本地会话杀进程树。"""
        if sid.startswith("web:"):
            app_id = sid[4:]
            return bool(self._web_client.disconnect(app_id).get("ok"))
        return self.runner.stop_tunnel(sid) if self.runner else False

    def remove_session(self, sid: str) -> bool:
        """移除会话：Web 会话会从 Web 面板删除该应用（需前端二次确认）。"""
        if sid.startswith("web:"):
            client = self._web_client
            app_id = sid[4:]
            client.disconnect(app_id)
            return bool(client.delete_app(app_id).get("ok"))
        return self.runner.remove_session(sid) if self.runner else False

    def list_sessions(self) -> list:
        """本地子进程会话 + 官方 Web 面板会话合并后的统一列表。

        合并后前端只需渲染一份列表，Web UI（http://localhost:8181/）里
        添加并连接的隧道就会出现在「活动会话」中。
        """
        local = self.runner.list_sessions() if self.runner else []
        for sess in local:
            sess.setdefault("source", "gui")
        merged = local + self._web_sessions()
        merged.sort(key=lambda s: (s.get("started_at") or 0), reverse=True)
        return merged

    def poll_log(self, sid: str, offset: int = 0) -> dict:
        if sid.startswith("web:"):
            return self._web_log(sid, offset)
        return self.runner.poll_log(sid, offset) if self.runner else {"exists": False}

    def _web_log(self, sid: str, offset: int) -> dict:
        """Web 会话没有进程日志流，这里给出状态摘要（同样支持 offset 增量）。"""
        sess = self.get_session(sid)
        if not sess:
            return {"exists": False}
        lines = [
            "[Web 面板会话] 该隧道由 Shield 官方 Web UI 管理，不提供进程日志流。",
            f"应用名称：{sess.get('display_name') or '—'}",
            f"目标地址：{sess.get('target') or '—'}",
            f"连接状态：{sess.get('raw_status') or sess.get('status') or '—'}",
        ]
        if sess.get("error"):
            lines.append(f"错误信息：{sess['error']}")
        urls = sess.get("access_urls") or []
        if urls:
            lines.append(f"访问地址：{urls[0]}")
        full = "\n".join(lines) + "\n"
        chunk = full[offset:] if offset < len(full) else ""
        return {
            "exists": True,
            "text": chunk,
            "total": len(full),
            "access_urls": list(urls),
            "status": sess.get("status"),
            "source": "web",
        }

    def get_session(self, sid: str) -> dict | None:
        """获取单个会话详情（含 argv 与可回填的表单参数）。"""
        if sid.startswith("web:"):
            for sess in self._web_sessions():
                if sess.get("session_id") == sid:
                    data = dict(sess)
                    data["editable"] = False
                    data["params"] = _parse_argv_params(
                        sess.get("argv") or [],
                        sess.get("protocol") or "",
                        sess.get("target") or "",
                        sess.get("display_name") or "",
                    )
                    return data
            return None
        sess = self.runner.get_session(sid) if self.runner else None
        if not sess:
            return None
        data = sess.to_dict()
        data["editable"] = True
        data["params"] = _parse_argv_params(
            sess.argv, sess.protocol, sess.target, sess.display_name
        )
        return data

    def update_session(self, sid: str, params: dict, restart: bool = False) -> dict:
        """编辑会话参数：更新 argv 记录，可选「保存并重启」立即生效。

        运行中只保存不重启时，返回 ``need_restart=True`` 提示前端；
        Web 面板会话由面板管理，这里拒绝修改并引导到面板编辑。
        """
        if sid.startswith("web:"):
            return {"error": "该会话由官方 Web 面板管理，请在面板中编辑"}
        if not self.runner:
            return {"error": "runner 未就绪"}
        sess = self.runner.get_session(sid)
        if not sess:
            return {"error": "会话不存在或已被移除"}

        p = self._merge_defaults(params or {})
        proto = (p.get("protocol") or sess.protocol or "ssh").strip()
        target = (p.get("target") or "").strip()
        display = (p.get("display_name") or "").strip()
        p["protocol"], p["target"], p["display_name"] = proto, target, display
        if not proto:
            return {"error": "请选择协议"}
        argv = _build_argv(p)

        old = (sess.argv, sess.protocol, sess.target, sess.display_name)
        running = (
            sess.status in _ACTIVE_STATUS
            and sess.process is not None
            and sess.process.poll() is None
        )
        self.runner.update_session_config(
            sid, argv=argv, protocol=proto, target=target,
            display_name=display,
        )

        if not restart:
            return {
                "ok": True,
                "session_id": sid,
                "argv": argv,
                "params": p,
                "need_restart": running,
                "status": sess.status,
            }

        # 保存并重启：先停旧进程，再用新 argv 起一个新会话并替换旧条目
        guard = self._check_limits(exclude_sids=(sid,))
        if guard:
            return {"error": guard, "limit": self.session_limits()}
        if running:
            self.runner.stop_tunnel(sid)
        cfg = self._network_config()
        res = self.runner.start_tunnel(
            argv, proto, target, display,
            env=self._child_env(cfg["proxy"]),
            server=self._server_of(argv, p),
        )
        if res.get("error") or res.get("status") == "error":
            # 启动失败：回滚参数到编辑前，避免旧会话带着半成品配置
            self.runner.update_session_config(
                sid, argv=old[0], protocol=old[1], target=old[2],
                display_name=old[3],
            )
            if res.get("session_id"):
                self.runner.remove_session(res["session_id"])
            return {"error": res.get("error") or "重启失败，请查看会话日志"}
        self.runner.remove_session(sid)
        res["restarted"] = True
        return res

    def restart_session(self, sid: str) -> dict:
        """重启会话：Web 会话重新 connect，本地会话复用原 argv 新建进程。"""
        if sid.startswith("web:"):
            app_id = sid[4:]
            # 同一应用重连不占新会话名额，但仍受并发上限约束
            running = [
                s for s in self.list_sessions()
                if s.get("status") in _ACTIVE_STATUS and s.get("session_id") != sid
            ]
            if len(running) >= MAX_RUNNING:
                return {
                    "error": (
                        f"同时连接数已达上限（最多 {MAX_RUNNING} 个），请先断开其他连接"
                    )
                }
            res = self._web_client.connect(app_id)
            if res.get("ok"):
                return {
                    "session_id": sid,
                    "access_urls": [res["site_url"]] if res.get("site_url") else [],
                    "source": "web",
                }
            return {"error": res.get("error") or "连接失败"}

        if not self.runner:
            return {"error": "runner 未就绪"}
        sess = self.runner.get_session(sid)
        if not sess:
            return {"error": "会话不存在"}
        if sess.status not in ("stopped", "error"):
            return {"error": "仅允许重启已停止的会话"}
        # 统一走重试链路：复用原 argv、继承代理配置与历史日志
        return self.retry_session(sid)

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
        # 端口同步：让会话合并去对接正确的 Web 面板
        try:
            self._web_port = int(port or WEBUI_DEFAULT_PORT)
            self._web_client = WebUIClient(self._web_port)
        except (TypeError, ValueError):
            pass
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
                self._web_client.invalidate()
                return {"ok": False, "message": "Web UI 未运行"}
            proc = self._web_ui_process
            if proc.poll() is not None:
                self._web_ui_process = None
                self._web_client.invalidate()
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
                self._web_client.invalidate()
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

    # 兜底直链（无网络获取元信息时使用；正常走 updater 的直链+镜像候选）
    DOWNLOAD_ZIP_URL = "https://github.com/fengyily/shield-cli/releases/latest/download/shield-windows-amd64.zip"
    INSTALL_BAT_URL = (
        "https://raw.githubusercontent.com/fengyily/shield-cli/main/install.bat"
    )
    INSTALL_DIR = r"C:\Program Files\ShieldCLI"

    def download_shield_release(self) -> dict:
        """下载 shield-windows-amd64.zip 并解压到安装目录。

        走 updater 的「直链 + 镜像」候选链路，国内网络也能装上。
        """
        install_dir = self.INSTALL_DIR
        mirrors = self._update_mirrors()
        try:
            os.makedirs(install_dir, exist_ok=True)
            zip_path = os.path.join(install_dir, "shield-windows-amd64.zip")
            asset = "shield-windows-amd64.zip"
            tag = ""
            try:
                rel = updater.fetch_release(updater.CLI_REPO, mirrors, timeout=6)
                tag = rel.get("tag_raw") or ""
                asset = updater.pick_asset(rel.get("assets") or [], "cli") or asset
            except Exception:  # noqa: BLE001 - 取不到元信息就用 latest 直链
                pass
            urls = updater.asset_candidates(updater.CLI_REPO, asset, tag, mirrors)
            dl = updater.download(urls, zip_path, min_bytes=200 * 1024)
            if not dl.get("ok"):
                return {
                    "ok": False,
                    "error": "下载失败：" + "；".join(
                        str(t) for t in (dl.get("tried") or [])[-3:]
                    ),
                }
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
        """保存设置（与已有配置合并，避免前端漏字段时丢掉镜像等配置）。"""
        if not self.store:
            return False
        merged = dict(self.store.load_settings() or {})
        merged.update(settings or {})
        ok = self.store.save_settings(merged)
        if ok:
            self._load_web_port()
        return ok

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

    def open_path(self, path: str = "") -> bool:
        """在资源管理器中定位文件（更新下载完成后引导用户查看）。"""
        if not path:
            return False
        try:
            target = os.path.abspath(path)
            if os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", target])
            elif os.path.isdir(target):
                subprocess.Popen(["explorer", target])
            else:
                folder = os.path.dirname(target)
                if os.path.isdir(folder):
                    subprocess.Popen(["explorer", folder])
                else:
                    return False
            return True
        except Exception:
            return False



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

    # 编辑会话时原样保留无法映射到表单的自定义参数
    extra = params.get("extra_argv") or []
    if isinstance(extra, (list, tuple)):
        argv += [str(x) for x in extra if str(x).strip()]

    return argv


# argv 中的 flag → 表单字段（与 _build_argv 一一对应）
_FLAG_FIELDS = {
    "--username": "username",
    "-u": "username",
    "--auth-pass": "auth_pass",
    "--private-key": "private_key",
    "--passphrase": "passphrase",
    "--db-name": "db_name",
    "--db-user": "db_user",
    "--db-pass": "db_pass",
    "--display-name": "display_name",
    "--site-name": "site_name",
    "--visable": "visable",
    "--tunnel-port": "tunnel_port",
    "--server": "server",
    "-H": "server",
}
_SWITCH_FIELDS = {
    "--enable-sftp": "enable_sftp",
    "--readonly": "readonly",
    "--invisible": "invisible",
    "--verbose": "verbose",
    "-v": "verbose",
}


def _parse_argv_params(
    argv: list, protocol: str = "", target: str = "", display_name: str = ""
) -> dict:
    """把 shield argv 反解成新建隧道表单的字段（供「编辑会话」回填）。

    无法映射到表单的未知参数收集进 ``extra_argv``，保存时原样追加，
    避免编辑一次就把自定义 flag 丢掉。
    """
    args = [str(a) for a in (argv or [])]
    proto = protocol or (args[0] if args else "ssh")
    params = {
        "protocol": proto,
        "target": target or "",
        "display_name": display_name or "",
        "username": "", "auth_pass": "", "private_key": "", "passphrase": "",
        "enable_sftp": False, "db_name": "", "db_user": "", "db_pass": "",
        "readonly": False, "site_name": "", "visable": "", "tunnel_port": "",
        "server": "", "invisible": False, "verbose": False,
        "extra_argv": [],
    }
    positional: list[str] = []
    i = 1 if args and not args[0].startswith("-") else 0
    while i < len(args):
        a = args[i]
        if a in _FLAG_FIELDS and i + 1 < len(args):
            params[_FLAG_FIELDS[a]] = args[i + 1]
            i += 2
            continue
        if a in _SWITCH_FIELDS:
            params[_SWITCH_FIELDS[a]] = True
            i += 1
            continue
        if a.startswith("-"):
            params["extra_argv"].append(a)
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                params["extra_argv"].append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        positional.append(a)
        i += 1
    if not params["target"] and positional:
        params["target"] = positional[0]
    return params


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
