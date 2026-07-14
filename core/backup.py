"""备份恢复管理：预设/全局数据打包、WebDAV 远程备份、定时调度。

备份文件格式: ShieldGUI_YYYYMMDD_HHMMSS.zip
  ├── apps.json          （Shield 官方预设）
  ├── presets.json       （GUI 兜底预设）
  ├── settings.json      （GUI 设置）
  └── info.json          （备份元数据：时间、版本）
"""

from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from datetime import datetime
from typing import Callable, Optional

# ── 默认备份路径（用户文档目录下） ──
_DEFAULT_BACKUP_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "ShieldGUI", "backups"
)

# ── Shield 官方预设路径 ──
_SHIELD_APPS_JSON = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ShieldCLI", "apps.json"
)

# ── GUI 兜底目录 ──
_GUI_FALLBACK_DIR = os.path.join(os.environ.get("APPDATA", ""), "ShieldGUI")


def _safe_read_json(path: str) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_write_json(path: str, data) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# =============================================================================
# BackupManager
# =============================================================================


class BackupManager:
    """管理本地/远程备份创建、恢复、定时调度。"""

    def __init__(self, on_notify: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            on_notify: 回调 (level, message) 用于向前端发通知
        """
        self._on_notify = on_notify
        self._scheduler_timer: Optional[threading.Timer] = None
        self._scheduler_running = False
        self._scheduler_interval_min = 0  # 0 = 关闭

    # ── 路径查询 ──

    def get_source_paths(self) -> dict:
        """返回可备份的源文件路径列表。"""
        paths = {}
        if os.path.isfile(_SHIELD_APPS_JSON):
            paths["apps.json"] = _SHIELD_APPS_JSON
        for name in ("presets.json", "settings.json"):
            p = os.path.join(_GUI_FALLBACK_DIR, name)
            if os.path.isfile(p):
                paths[name] = p
        return paths

    def get_default_backup_dir(self) -> str:
        return _DEFAULT_BACKUP_DIR

    def get_shield_apps_path(self) -> str:
        return _SHIELD_APPS_JSON

    # ── 创建备份 ──

    def create_backup(self, backup_dir: str | None = None) -> dict:
        """创建完整备份，返回 {ok, path, name, error}。"""
        backup_dir = backup_dir or _DEFAULT_BACKUP_DIR
        os.makedirs(backup_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"ShieldGUI_{ts}.zip"
        zip_path = os.path.join(backup_dir, name)

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 源文件
                for arcname, src in self.get_source_paths().items():
                    zf.write(src, arcname)
                # info.json
                info = {
                    "created_at": datetime.now().isoformat(),
                    "gui_version": "1.0.0",
                    "files": list(self.get_source_paths().keys()),
                }
                zf.writestr("info.json", json.dumps(info, indent=2))
            self._notify("success", f"备份成功: {name}")
            return {"ok": True, "path": zip_path, "name": name}
        except Exception as e:
            self._notify("error", f"备份失败: {e}")
            return {"ok": False, "error": str(e)}

    # ── 恢复备份 ──

    def restore_backup(self, zip_path: str) -> dict:
        """从 zip 恢复预设和设置文件。"""
        if not os.path.isfile(zip_path):
            return {"ok": False, "error": "备份文件不存在"}

        restored = []
        errors = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    if name == "info.json":
                        continue
                    # 恢复 apps.json 到 Shield 目录
                    if name == "apps.json":
                        dst = _SHIELD_APPS_JSON
                    else:
                        dst = os.path.join(_GUI_FALLBACK_DIR, name)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(zf.read(name))
                    restored.append(name)
            self._notify("success", f"恢复完成，共 {len(restored)} 个文件")
            return {"ok": True, "restored": restored}
        except Exception as e:
            self._notify("error", f"恢复失败: {e}")
            return {"ok": False, "error": str(e)}

    # ── 列出备份 ──

    def list_backups(self, backup_dir: str | None = None) -> list[dict]:
        """列出备份目录中的所有 ShieldGUI_*.zip 文件。"""
        backup_dir = backup_dir or _DEFAULT_BACKUP_DIR
        if not os.path.isdir(backup_dir):
            return []
        results = []
        try:
            for fn in sorted(os.listdir(backup_dir), reverse=True):
                if fn.startswith("ShieldGUI_") and fn.endswith(".zip"):
                    fp = os.path.join(backup_dir, fn)
                    stat = os.stat(fp)
                    results.append(
                        {
                            "name": fn,
                            "path": fp,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(
                                stat.st_mtime
                            ).isoformat(),
                        }
                    )
        except Exception:
            pass
        return results

    def delete_backup(self, zip_path: str) -> dict:
        """删除指定备份文件。"""
        try:
            if os.path.isfile(zip_path):
                os.remove(zip_path)
                return {"ok": True}
            return {"ok": False, "error": "文件不存在"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── WebDAV 远程备份 ──

    def _webdav_request(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        username: str = "",
        password: str = "",
    ) -> tuple[int, bytes]:
        """底层 WebDAV HTTP 请求（基于 urllib）。"""
        import urllib.request
        import base64

        req = urllib.request.Request(url, data=data, method=method)
        if username and password:
            auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            req.add_header("Authorization", f"Basic {auth}")
        req.add_header("User-Agent", "ShieldGUI/1.0")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            return 0, str(e).encode()

    @staticmethod
    def _webdav_subdir() -> str:
        """WebDAV 远程子目录名称。"""
        return "ShieldGUI"

    def _webdav_url(self, base_url: str, filename: str = "") -> str:
        """拼接 WebDAV 完整 URL，自动追加 ShieldGUI 子目录。"""
        url = base_url.rstrip("/")
        sub = self._webdav_subdir()
        if filename:
            return f"{url}/{sub}/{filename}"
        return f"{url}/{sub}"

    def _webdav_mkcol(self, dir_url: str, username: str, password: str) -> bool:
        """通过 MKCOL 创建远程目录，已存在时返回 True。"""
        code, body = self._webdav_request(
            dir_url,
            method="MKCOL",
            username=username,
            password=password,
        )
        # 201=Created, 405=MethodNotAllowed/已存在, 200=OK
        return code in (200, 201, 405)

    def webdav_upload(self, local_path: str, config: dict) -> dict:
        """通过 WebDAV PUT 上传备份（自动创建 ShieldGUI 目录）。"""
        url = config.get("url", "")
        if not url:
            return {"ok": False, "error": "WebDAV URL 未配置"}
        username = config.get("username", "")
        password = config.get("password", "")
        name = os.path.basename(local_path)
        remote_url = self._webdav_url(url, name)

        # 先确保远程 ShieldGUI/ 目录存在
        dir_url = self._webdav_url(url)
        self._webdav_mkcol(dir_url, username, password)

        try:
            with open(local_path, "rb") as f:
                data = f.read()
            code, body = self._webdav_request(
                remote_url,
                method="PUT",
                data=data,
                username=username,
                password=password,
            )
            if 200 <= code < 300:
                self._notify("success", f"已上传到 WebDAV: {name}")
                return {"ok": True}
            return {
                "ok": False,
                "error": f"HTTP {code}: {body.decode(errors='replace')[:200]}",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def webdav_download(self, filename: str, local_dir: str, config: dict) -> dict:
        """从 WebDAV GET 下载备份并恢复到 local_dir。"""
        url = config.get("url", "")
        if not url:
            return {"ok": False, "error": "WebDAV URL 未配置"}
        username = config.get("username", "")
        password = config.get("password", "")
        remote_url = self._webdav_url(url, filename)
        local_path = os.path.join(local_dir, filename)

        try:
            code, body = self._webdav_request(
                remote_url,
                method="GET",
                username=username,
                password=password,
            )
            if code != 200:
                return {"ok": False, "error": f"HTTP {code}: 下载失败"}
            os.makedirs(local_dir, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(body)
            return {"ok": True, "path": local_path}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def webdav_list(self, config: dict) -> list[dict]:
        """列出 WebDAV 远程 ShieldGUI 目录下的备份文件（PROPFIND）。"""
        url = config.get("url", "")
        if not url:
            return []
        username = config.get("username", "")
        password = config.get("password", "")
        import xml.etree.ElementTree as ET

        remote_url = self._webdav_url(url)
        body = (
            '<?xml version="1.0"?>'
            '<d:propfind xmlns:d="DAV:">'
            "<d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/></d:prop>"
            "</d:propfind>"
        ).encode()
        code, resp_body = self._webdav_request(
            remote_url,
            method="PROPFIND",
            data=body,
            username=username,
            password=password,
        )
        if code not in (207, 200):
            return []
        files = []
        try:
            root = ET.fromstring(resp_body)
            ns = {"d": "DAV:"}
            for resp_el in root.findall(".//d:response", ns):
                href_el = resp_el.find("d:href", ns)
                if href_el is None or href_el.text is None:
                    continue
                fname = href_el.text.rstrip("/").split("/")[-1]
                if not fname.startswith("ShieldGUI_") or not fname.endswith(".zip"):
                    continue
                prop = resp_el.find("d:propstat/d:prop", ns)
                size_el = (
                    prop.find("d:getcontentlength", ns) if prop is not None else None
                )
                size = int(size_el.text) if size_el is not None and size_el.text else 0
                files.append({"name": fname, "size": size})
        except Exception:
            pass
        return files

    # ── 定时备份调度 ──

    def scheduler_start(
        self,
        interval_minutes: int,
        backup_dir: str | None = None,
        webdav_config: dict | None = None,
    ) -> None:
        """启动定时备份（单位：分钟，0 = 关闭）。"""
        self.scheduler_stop()
        if interval_minutes <= 0:
            self._scheduler_interval_min = 0
            return
        self._scheduler_interval_min = interval_minutes
        self._scheduler_running = True
        self._scheduler_loop(backup_dir, webdav_config)

    def scheduler_stop(self) -> None:
        self._scheduler_running = False
        if self._scheduler_timer:
            self._scheduler_timer.cancel()
            self._scheduler_timer = None

    def scheduler_status(self) -> dict:
        return {
            "running": self._scheduler_running,
            "interval_min": self._scheduler_interval_min,
        }

    def _scheduler_loop(
        self, backup_dir: str | None = None, webdav_config: dict | None = None
    ) -> None:
        if not self._scheduler_running or self._scheduler_interval_min <= 0:
            return
        # 执行备份
        result = self.create_backup(backup_dir)
        if (
            result.get("ok")
            and webdav_config
            and webdav_config.get("enabled")
            and webdav_config.get("url")
        ):
            self.webdav_upload(result["path"], webdav_config)
        # 设定下次
        self._scheduler_timer = threading.Timer(
            self._scheduler_interval_min * 60,
            self._scheduler_loop,
            args=(backup_dir, webdav_config),
        )
        self._scheduler_timer.daemon = True
        self._scheduler_timer.start()

    # ── 通知 ──

    def _notify(self, level: str, msg: str) -> None:
        if self._on_notify:
            try:
                self._on_notify(level, msg)
            except Exception:
                pass
