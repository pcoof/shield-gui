"""Shield CLI 更新前的进程清理。

更新 ``shield.exe`` 时，任何仍在运行的 shield.exe 都会锁住目标文件：
GUI 启动的隧道子进程、``shield start`` Web 面板、系统托盘、
命令行手动启动的实例，以及注册成 Windows 服务的实例。
只停掉 GUI 自己管的进程不够，外部实例照样会让 ``os.replace`` 失败，
或者出现「文件换了、内存里还跑着旧版本」的情况。

本模块负责四件事：

1. 枚举全部 ``shield.exe`` 进程（PowerShell / WMI 为主，tasklist 兜底）
2. 停止 ShieldCLI 服务（如果已安装且在运行）
3. ``taskkill /F /T`` 结束进程树并等待确认退出
4. 等待目标文件解除占用（可写检测）后再允许替换

纯标准库实现，不引入 psutil 等新依赖。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
import time

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
EXE_NAME = "shield.exe"
SERVICE_NAME = "ShieldCLI"

# 用 WMI 拿 ExecutablePath / CommandLine，才能区分安装目录与外部副本，
# 并在更新完成后从命令行还原原先的 Web 面板端口。
_PS_SCRIPT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Get-CimInstance Win32_Process -Filter \"Name='shield.exe'\" | "
    "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | "
    "ConvertTo-Json -Compress -Depth 2"
)


def _run(args: list[str], timeout: float = 12.0) -> str:
    """执行外部命令并返回 stdout（隐藏控制台窗口）。"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return (result.stdout or "").strip()
    except Exception:  # noqa: BLE001 - 查询失败一律走兜底通道
        return ""


def _normalize_rows(raw: object) -> list[dict]:
    """把 WMI 的 JSON 结果（单个对象或数组）整理成进程记录。"""
    rows = raw if isinstance(raw, list) else [raw]
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId") or 0)
            ppid = int(row.get("ParentProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        out.append(
            {
                "pid": pid,
                "ppid": ppid,
                "exe": str(row.get("ExecutablePath") or ""),
                "cmd": str(row.get("CommandLine") or ""),
            }
        )
    return out


def _list_via_powershell() -> list[dict] | None:
    """返回 None 表示查询失败（需换兜底），返回 [] 表示确实没有进程。"""
    out = _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT]
    )
    if not out:
        # 命令本身没输出：可能是 PowerShell 不可用，也可能是没有匹配进程。
        # 用 tasklist 复核一次，避免把「查询失败」误判成「没有进程」。
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        # PowerShell 偶尔会带 CLIXML / 进度噪声，截取首尾为 JSON 的部分
        match = re.search(r"[\[{].*[\]}]", out, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return _normalize_rows(data)


def _list_via_tasklist() -> list[dict]:
    out = _run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV", "/NH"])
    procs: list[dict] = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) < 2 or row[0].strip().lower() != EXE_NAME:
            continue
        try:
            pid = int(row[1].strip().replace(",", ""))
        except ValueError:
            continue
        procs.append({"pid": pid, "ppid": 0, "exe": "", "cmd": ""})
    return procs


def list_shield_processes() -> list[dict]:
    """列出所有 shield.exe 进程（自动排除 GUI 自身，避免误杀）。"""
    if not IS_WIN:
        return []
    procs = _list_via_powershell()
    if procs is None:
        procs = _list_via_tasklist()
    own_pid = os.getpid()
    try:
        own_exe = os.path.normcase(os.path.abspath(sys.executable))
    except Exception:  # noqa: BLE001
        own_exe = ""
    result = []
    for proc in procs:
        if proc["pid"] == own_pid:
            continue
        if own_exe and proc["exe"]:
            if os.path.normcase(os.path.abspath(proc["exe"])) == own_exe:
                continue
        result.append(proc)
    return result


def _pid_alive(pid: int) -> bool:
    out = _run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], timeout=6.0)
    # tasklist 输出形如 "shield.exe  21104 Console ..."
    return bool(re.search(rf"(?<!\d){pid}(?!\d)", out))


def describe(proc: dict) -> str:
    """把进程记录压成一句可读描述，便于进度条/错误提示。"""
    cmd = (proc.get("cmd") or "").replace('"', "").strip()
    if len(cmd) > 70:
        cmd = cmd[:67] + "…"
    return f"PID {proc['pid']}" + (f" ({cmd})" if cmd else "")


def stop_cli_service(name: str = SERVICE_NAME) -> dict:
    """停止 Windows 服务（服务会独立持有 shield.exe 句柄）。"""
    if not IS_WIN:
        return {"installed": False, "running": False, "stopped": True}
    try:
        query = _run(["sc", "query", name], timeout=8.0)
        if "SERVICE_NAME" not in query:
            return {
                "installed": False, "was_running": False,
                "running": False, "stopped": True,
            }
        if "RUNNING" not in query:
            return {
                "installed": True, "was_running": False,
                "running": False, "stopped": True,
            }
        _run(["sc", "stop", name], timeout=15.0)
        for _ in range(12):
            state = _run(["sc", "query", name], timeout=8.0)
            if "STOPPED" in state:
                return {
                    "installed": True, "was_running": True,
                    "running": False, "stopped": True,
                }
            time.sleep(0.5)
        return {
            "installed": True, "was_running": True,
            "running": True, "stopped": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "installed": False, "was_running": False,
            "running": False, "stopped": False, "error": str(exc),
        }


def start_cli_service(name: str = SERVICE_NAME) -> bool:
    """更新后恢复之前被停掉的 Windows 服务。"""
    if not IS_WIN:
        return False
    out = _run(["sc", "start", name], timeout=15.0)
    # sc start 成功输出里含 STATE / START_PENDING，失败含错误码
    if "START_PENDING" in out or "RUNNING" in out:
        return True
    for _ in range(10):
        state = _run(["sc", "query", name], timeout=8.0)
        if "RUNNING" in state:
            return True
        time.sleep(0.4)
    return False


def wait_file_writable(path: str, timeout: float = 8.0) -> bool:
    """等待目标 exe 解除占用（以读写方式打开但不改动内容）。"""
    if not path or not os.path.isfile(path):
        return True
    deadline = time.time() + timeout
    while True:
        try:
            with open(path, "r+b"):
                return True
        except OSError:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(0.4)


def terminate_all(target_exe: str = "", timeout: float = 8.0) -> dict:
    """结束所有 shield.exe 进程 + 停止服务 + 等待文件解除占用。

    返回 ``{found, killed, failed, survivors, service, file_writable, ports, details}``。
    ``ports`` 是从被结束进程命令行里解析出的 Web 面板端口，供更新后恢复使用。
    """
    procs = list_shield_processes()
    ports: list[int] = []
    for proc in procs:
        # 只认 `shield start <port>` 这种 Web 面板命令行；隧道参数里的
        # --port / tunnel_port 不是面板端口，不能拿去恢复服务。
        for match in re.finditer(r"\bstart\s+(\d{2,5})\b", proc["cmd"], re.I):
            try:
                port = int(match.group(1))
            except ValueError:
                continue
            if 1 <= port <= 65535 and port not in ports:
                ports.append(port)

    service = stop_cli_service()
    killed: list[dict] = []
    failed: list[dict] = []
    for proc in procs:
        pid = proc["pid"]
        if not _pid_alive(pid):
            # 已被上一个 /T 进程树连带结束
            killed.append(proc)
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=8.0,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            proc = dict(proc, error=str(exc))
        # 给系统一点时间回收句柄
        for _ in range(8):
            if not _pid_alive(pid):
                break
            time.sleep(0.25)
        (failed if _pid_alive(pid) else killed).append(proc)

    survivors = list_shield_processes()
    file_writable = wait_file_writable(target_exe, timeout=timeout)
    return {
        "found": len(procs),
        "killed": killed,
        "failed": failed,
        "survivors": survivors,
        "service": service,
        "file_writable": file_writable,
        "ports": ports,
        "details": [describe(p) for p in procs],
    }
