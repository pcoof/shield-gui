"""Shield CLI 调用器：长连接子进程管理 + 一次性命令执行。

职责：
- start_tunnel: spawn `shield <proto> [ip:port] [flags]`，后台采集日志
- stop_tunnel: 终止子进程（含子进程树）
- list_sessions / poll_log: 会话状态与日志查询
- run_cli: 一次性命令（plugin/install/stop/uninstall/clean 等）
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import net_diag

IS_WIN = os.name == "nt"
# Windows 下隐藏控制台窗口
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

# shield 输出中识别公网 Access URL
# 优先匹配 yishield 域名（避免 banner 里的 github.com 等被误识别）；
# 同时保留通用 http(s) URL 作为兜底。
URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*(?:yishield\.com|shieldcli\.[a-z]+|localhost(?::\d+)?)/[^\s\"'<>\x1b]*"
    r"|https?://[a-z0-9.-]+\.yishield\.[a-z]+(?:/[^\s\"'<>]*)?",
    re.IGNORECASE,
)
# 通用 URL（仅在 yishield 域名未命中时使用，且排除 banner 常见噪音域名）
URL_RE_FALLBACK = re.compile(r"https?://(?!github\.com|golang\.org)[^\s\"'<>\x1b]+", re.IGNORECASE)
# ANSI 转义码（颜色/光标），渲染前去除以免显示成 [36m 之类
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07")


@dataclass
class Session:
    session_id: str
    protocol: str
    target: str
    argv: list
    process: Optional[subprocess.Popen] = None
    log_buffer: str = ""
    access_urls: list = field(default_factory=list)
    status: str = "starting"  # starting | running | stopped | error
    started_at: float = 0.0
    ended_at: float = 0.0
    display_name: str = ""
    # 启动失败时的结构化中文诊断（net_diag.diagnose_log 的结果）
    error_info: Optional[dict] = None
    # CLI 内部重试提示，例如「第 2/5 次尝试失败，正在重试…」
    warning: str = ""
    # GUI 自动重试次数（避免无限重启）
    retry_count: int = 0
    # 本次连接使用的服务器地址（便于诊断展示）
    server: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "protocol": self.protocol,
            "target": self.target,
            "argv": self.argv,
            "access_urls": self.access_urls,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "display_name": self.display_name,
            "log_size": len(self.log_buffer),
            "pid": self.process.pid if self.process else None,
            "error_info": self.error_info,
            "error": self.error_info.get("title") if self.error_info else "",
            "warning": self.warning,
            "retry_count": self.retry_count,
            "server": self.server,
        }


class ShieldRunner:
    """所有 shield.exe 调用的统一入口。"""

    LOG_CAP = 256 * 1024  # 单会话日志上限 256KB，超出滚动

    def __init__(self, shield_exe: str, on_error: Optional[Callable] = None):
        self.shield_exe = shield_exe
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        # 会话启动失败回调 (sid, diagnosis) -> None，由 PythonApi 注入
        self.on_error = on_error

    # ---------- 长连接隧道 ----------

    def start_tunnel(self, argv: list, protocol: str, target: str,
                     display_name: str = "", env: Optional[dict] = None,
                     server: str = "", retry_count: int = 0) -> dict:
        """启动一个隧道子进程。argv 已是完整参数列表（不含 exe 路径）。

        ``env`` 为完整子进程环境（可含 HTTP_PROXY 等，Go net/http 会读取）；
        ``server`` 仅用于诊断展示；``retry_count`` 用于限制自动重试次数。
        """
        full_argv = [self.shield_exe] + list(argv)
        sid = uuid.uuid4().hex[:12]
        session = Session(
            session_id=sid,
            protocol=protocol,
            target=target,
            argv=list(argv),
            display_name=display_name or f"{protocol} {target}",
            started_at=time.time(),
            server=server,
            retry_count=retry_count,
        )
        try:
            popen_kw = dict(
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
            if env:
                popen_kw["env"] = env
            proc = subprocess.Popen(full_argv, **popen_kw)
        except Exception as exc:  # 启动失败
            session.status = "error"
            session.log_buffer = f"[启动失败] {exc}\n"
            session.ended_at = time.time()
            with self._lock:
                self._sessions[sid] = session
            return session.to_dict()

        session.process = proc
        session.status = "running"
        with self._lock:
            self._sessions[sid] = session

        # 后台线程持续读输出
        t = threading.Thread(target=self._reader, args=(sid,), daemon=True)
        t.start()
        # 监控进程结束
        t2 = threading.Thread(target=self._watcher, args=(sid,), daemon=True)
        t2.start()
        return session.to_dict()

    def _reader(self, sid: str) -> None:
        session = self._sessions.get(sid)
        if not session or not session.process:
            return
        try:
            for line in session.process.stdout:
                if not line:
                    break
                # 去 ANSI 颜色码，避免前端显示成 [36m
                clean = ANSI_RE.sub("", line)
                with self._lock:
                    session.log_buffer += clean
                    if len(session.log_buffer) > self.LOG_CAP:
                        # 滚动：保留后半段
                        session.log_buffer = (
                            "...[日志已截断]...\n" + session.log_buffer[-self.LOG_CAP // 2 :]
                        )
                    # 提取 Access URL（优先 yishield 域名，再兜底通用 URL）
                    urls = URL_RE.findall(clean) or URL_RE_FALLBACK.findall(clean)
                    for u in urls:
                        u = u.rstrip(".,;:)")  # 去尾部标点
                        if u not in session.access_urls:
                            session.access_urls.append(u)
                    # CLI 内部重试：只更新提示，不判定为最终失败
                    attempt = net_diag.parse_retry_attempt(clean)
                    if attempt:
                        session.warning = (
                            f"quick-setup 第 {attempt[0]}/{attempt[1]} 次尝试失败，"
                            "CLI 正在自动重试…"
                        )
                    snapshot = session.log_buffer
                # CLI 明确宣告失败时立刻纠正状态，别让 UI 继续显示「运行中」
                if net_diag.is_fatal_line(clean) and session.error_info is None:
                    diag = net_diag.diagnose_log(snapshot)
                    if diag:
                        self._mark_error(sid, diag)
        except Exception:
            pass

    def _mark_error(self, sid: str, diag: dict) -> None:
        """标记会话失败：纠正状态、写入中文诊断、回调通知前端。"""
        with self._lock:
            session = self._sessions.get(sid)
            if not session or session.error_info:
                return
            session.error_info = diag
            session.warning = ""
            # 进程若仍显示 running，纠正为 error（CLI 通常随后自行退出）
            if session.status in ("running", "starting"):
                session.status = "error"
            session.log_buffer += net_diag.format_diagnosis(diag)
        if self.on_error:
            # 单独线程执行，避免阻塞日志读取线程
            threading.Thread(
                target=self._safe_notify, args=(sid, diag), daemon=True
            ).start()

    def _safe_notify(self, sid: str, diag: dict) -> None:
        try:
            self.on_error(sid, diag)
        except Exception:  # noqa: BLE001 - 通知失败不能影响会话
            pass

    def _watcher(self, sid: str) -> None:
        session = self._sessions.get(sid)
        if not session or not session.process:
            return
        rc = session.process.wait()
        with self._lock:
            session.ended_at = time.time()
            session.status = "error" if (rc not in (0, None) or session.error_info) else "stopped"
            session.log_buffer += f"\n[进程结束，退出码 {rc}]\n"
            snapshot = session.log_buffer
            has_diag = session.error_info is not None
        # 兜底：CLI 没打印明确的失败行，但非零退出且有错误输出
        if not has_diag and rc not in (0, None):
            diag = net_diag.diagnose_log(snapshot)
            if diag:
                self._mark_error(sid, diag)

    def stop_tunnel(self, sid: str) -> bool:
        with self._lock:
            session = self._sessions.get(sid)
        if not session or not session.process:
            return False
        if session.process.poll() is not None:
            return True  # 已经结束
        try:
            _kill_tree(session.process.pid)
            try:
                session.process.wait(timeout=3)
            except Exception:
                session.process.kill()
        except Exception as exc:
            with self._lock:
                session.log_buffer += f"\n[停止失败] {exc}\n"
            return False
        return True

    def list_sessions(self) -> list:
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def get_session(self, sid: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(sid)

    def update_session_config(self, sid: str, **fields) -> bool:
        """原地更新会话参数（argv/protocol/target/display_name 等）。

        仅修改记录，不触碰正在运行的进程；参数在下次启动/重启时生效。
        """
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return False
            for key, value in fields.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            return True

    def poll_log(self, sid: str, offset: int = 0) -> dict:
        """返回从 offset 开始的日志增量，便于前端轮询拉取。"""
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return {"exists": False}
            full = session.log_buffer
            chunk = full[offset:] if offset < len(full) else ""
            return {
                "exists": True,
                "text": chunk,
                "total": len(full),
                "access_urls": list(session.access_urls),
                "status": session.status,
                "error_info": session.error_info,
                "warning": session.warning,
            }

    def seed_log(self, sid: str, text: str) -> None:
        """重试时把上一次的诊断日志带到新会话，方便对照。"""
        with self._lock:
            session = self._sessions.get(sid)
            if session:
                session.log_buffer = text

    def remove_session(self, sid: str) -> bool:
        self.stop_tunnel(sid)
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    # ---------- 一次性命令 ----------

    def run_cli(self, argv: list, timeout: int = 60) -> dict:
        """同步执行一次性命令，等执行完返回完整输出。"""
        full_argv = [self.shield_exe] + list(argv)
        try:
            proc = subprocess.run(
                full_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                cwd=os.path.dirname(self.shield_exe) or None,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return {
                "code": proc.returncode,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
            }
        except subprocess.TimeoutExpired:
            return {"code": -1, "stdout": "", "stderr": f"命令执行超时（{timeout}s）"}
        except Exception as exc:
            return {"code": -1, "stdout": "", "stderr": str(exc)}


def _kill_tree(pid: int) -> None:
    """Windows 下杀整个进程树。"""
    if not IS_WIN:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=10,
        )
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
