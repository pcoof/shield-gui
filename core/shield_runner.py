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
from typing import Optional

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
        }


class ShieldRunner:
    """所有 shield.exe 调用的统一入口。"""

    LOG_CAP = 256 * 1024  # 单会话日志上限 256KB，超出滚动

    def __init__(self, shield_exe: str):
        self.shield_exe = shield_exe
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    # ---------- 长连接隧道 ----------

    def start_tunnel(self, argv: list, protocol: str, target: str,
                     display_name: str = "") -> dict:
        """启动一个隧道子进程。argv 已是完整参数列表（不含 exe 路径）。"""
        full_argv = [self.shield_exe] + list(argv)
        sid = uuid.uuid4().hex[:12]
        session = Session(
            session_id=sid,
            protocol=protocol,
            target=target,
            argv=list(argv),
            display_name=display_name or f"{protocol} {target}",
            started_at=time.time(),
        )
        try:
            proc = subprocess.Popen(
                full_argv,
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
        except Exception:
            pass

    def _watcher(self, sid: str) -> None:
        session = self._sessions.get(sid)
        if not session or not session.process:
            return
        rc = session.process.wait()
        with self._lock:
            session.ended_at = time.time()
            session.status = "stopped" if rc in (0, None) else "error"
            session.log_buffer += f"\n[进程结束，退出码 {rc}]\n"

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
            }

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
