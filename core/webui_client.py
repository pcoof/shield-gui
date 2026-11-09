"""Shield 官方 Web UI（``shield start``）HTTP API 客户端。

作用：把浏览器里 http://localhost:8181/ 添加的应用（apps）与连接状态
映射成 GUI 的会话模型，从而让 Web 面板里创建的隧道也出现在
「活动会话」列表中（source = "web"）。

已探测到的官方接口（shield-cli 0.3.11）：
  GET    /api/version
  GET    /api/apps                → {"code":200,"data":[app...]}
  GET    /api/apps/{id}
  POST   /api/apps                (新建应用)
  PUT    /api/apps/{id}
  DELETE /api/apps/{id}
  POST   /api/connect/{id}        → data.site_url
  POST   /api/disconnect/{id}
  GET    /api/status/{id}         → {"status":"connected|connecting|failed","error":"..."}
  GET    /api/protocols
  GET    /api/plugins

app 字段：id / name / protocol / ip / port / server / tunnel_port / visable /
invisible / site_name / db_readonly / created_at / updated_at /
last_connected_at / conn_status{status, site_url?, error?}
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_PORT = 8181
USER_AGENT = "ShieldGUI/1.0"
# 端口探测结果缓存时间（秒）：避免 Web UI 未启动时每次轮询都等超时
_AVAIL_TTL = 6.0
# apps 列表缓存时间（秒）：2 秒轮询下不重复打接口
_APPS_TTL = 1.2

# Web 面板的连接状态 → GUI 会话状态
_STATUS_MAP = {
    "connected": "running",
    "connecting": "starting",
    "disconnecting": "stopped",
    "disconnected": "stopped",
    "failed": "error",
    "error": "error",
    "timeout": "error",
}


def _parse_ts(value: str) -> float:
    """解析 Go 的 RFC3339 时间串（可能带 7 位纳秒）为 Unix 秒。"""
    if not value:
        return 0.0
    txt = str(value).strip()
    # 收窄小数位到 6 位，兼容 Python fromisoformat
    txt = re.sub(r"\.(\d{6})\d+", r".\1", txt)
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z"),
        lambda s: datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"),
    ):
        try:
            return parser(txt).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0


class WebUIClient:
    """与官方 Web 面板通信的轻量客户端（纯标准库，短超时）。"""

    def __init__(self, port: int = DEFAULT_PORT, timeout: float = 2.0):
        self.port = int(port or DEFAULT_PORT)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._avail_at = 0.0
        self._avail = False
        self._apps_at = 0.0
        self._apps_cache: list[dict] = []
        self._version_cache = ""

    # ---------- 基础 ----------

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _port_open(self, timeout: float = 0.25) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def is_available(self, force: bool = False) -> bool:
        """Web UI 是否在线（带 6 秒缓存）。"""
        now = time.time()
        with self._lock:
            if not force and now - self._avail_at < _AVAIL_TTL:
                return self._avail
        alive = self._port_open()
        with self._lock:
            self._avail = alive
            self._avail_at = now
            if not alive:
                self._apps_cache = []
                self._apps_at = 0.0
        return alive

    def _request(
        self, path: str, method: str = "GET", payload: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        url = self.base + path
        data = None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(
            req, timeout=timeout if timeout is not None else self.timeout
        ) as resp:
            raw = resp.read()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {}

    # ---------- 查询 ----------

    def version(self) -> str:
        if self._version_cache:
            return self._version_cache
        try:
            data = self._request("/api/version", timeout=1.5)
            self._version_cache = str(data.get("version") or "")
        except Exception:  # noqa: BLE001
            self._version_cache = ""
        return self._version_cache

    def apps(self, force: bool = False) -> list[dict]:
        """返回 Web 面板里的应用列表（带 1.2 秒缓存）。"""
        now = time.time()
        with self._lock:
            if not force and now - self._apps_at < _APPS_TTL:
                return list(self._apps_cache)
        if not self.is_available():
            return []
        try:
            data = self._request("/api/apps", timeout=max(1.5, self.timeout))
            items = data.get("data")
            if not isinstance(items, list):
                items = []
        except Exception:  # noqa: BLE001 - Web UI 抖动不应影响 GUI
            items = []
        with self._lock:
            self._apps_cache = items
            self._apps_at = now
        return list(items)

    def status(self, app_id: str) -> dict:
        try:
            data = self._request(f"/api/status/{app_id}", timeout=2.0)
            inner = data.get("data")
            return inner if isinstance(inner, dict) else data
        except Exception:  # noqa: BLE001
            return {}

    # ---------- 操作 ----------

    def connect(self, app_id: str) -> dict:
        try:
            data = self._request(f"/api/connect/{app_id}", method="POST", payload={})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        code = data.get("code", 200)
        ok = code == 200 and not inner.get("error")
        self.invalidate()
        return {
            "ok": ok,
            "site_url": inner.get("site_url", ""),
            "error": "" if ok else (inner.get("error") or data.get("message") or f"code={code}"),
        }

    def disconnect(self, app_id: str) -> dict:
        try:
            data = self._request(
                f"/api/disconnect/{app_id}", method="POST", payload={}
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        self.invalidate()
        code = data.get("code", 200)
        return {
            "ok": code == 200,
            "error": "" if code == 200 else (data.get("message") or f"code={code}"),
        }

    def delete_app(self, app_id: str) -> dict:
        try:
            data = self._request(f"/api/apps/{app_id}", method="DELETE")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        self.invalidate()
        code = data.get("code", 200)
        return {
            "ok": code == 200,
            "error": "" if code == 200 else (data.get("message") or f"code={code}"),
        }

    def invalidate(self) -> None:
        with self._lock:
            self._apps_at = 0.0
            self._avail_at = 0.0

    # ---------- 映射为 GUI 会话 ----------

    def sessions(self) -> list[dict]:
        """把 Web 面板应用映射成与 ShieldRunner.Session.to_dict 同构的会话。"""
        return [self.app_to_session(a) for a in self.apps() if a.get("id")]

    @staticmethod
    def app_to_session(app: dict) -> dict:
        conn = app.get("conn_status") or {}
        raw = str(conn.get("status") or "").lower()
        status = _STATUS_MAP.get(raw, "stopped")

        ip = str(app.get("ip") or "")
        port = app.get("port") or 0
        target = f"{ip}:{port}" if ip and port else (ip or str(port or ""))

        urls: list[str] = []
        site = conn.get("site_url") or ""
        if site:
            urls.append(site)

        started = _parse_ts(app.get("last_connected_at") or "") or _parse_ts(
            app.get("created_at") or ""
        )
        live = status in ("running", "starting")

        return {
            "session_id": "web:" + str(app.get("id")),
            "protocol": app.get("protocol") or "",
            "target": target,
            "argv": [],
            "access_urls": urls,
            "status": status,
            "started_at": started,
            "ended_at": 0.0 if live else _parse_ts(app.get("updated_at") or ""),
            "display_name": app.get("name") or "",
            "log_size": 0,
            "pid": None,
            # —— 以下为 Web 会话扩展字段 ——
            "source": "web",
            "web_id": str(app.get("id")),
            "raw_status": raw,
            "error": conn.get("error") or "",
            "server": app.get("server") or "",
            "web_managed": True,
        }


def probe_port(port: int) -> bool:
    """快速判断某端口是否有服务监听。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False
