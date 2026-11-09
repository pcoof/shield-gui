"""更新通道：Release 元信息多通道获取 + 直链/镜像下载 + Windows 原地替换。

目标：不再让用户跳转 GitHub 网页，而是直接在应用内下载新版本并替换。

元信息获取顺序（前一个失败才降级到下一个）：
  1. https://api.github.com/repos/<repo>/releases/latest          直连
  2. <镜像前缀> + api.github.com（ghproxy 类镜像可透传 API）
  3. <镜像前缀> + github.com/<repo>/releases/latest 跟随 302 取 tag
     —— 拿不到资产列表时用 releases/download/<tag>/<已知资产名> 兜底拼直链

下载链接候选（按顺序探测，第一个可用的就用）：
  直链 → https://ghproxy.net/<直链> → https://v4.gh-proxy.org/<直链>
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
DETACHED_PROCESS = 0x00000008 if IS_WIN else 0

GITHUB = "https://github.com"
API = "https://api.github.com"
USER_AGENT = "ShieldGUI-Updater/1.0"

# GUI 自身仓库与 CLI 仓库
GUI_REPO = "pcoof/shield-gui"
CLI_REPO = "fengyily/shield-cli"

# 默认镜像前缀（把完整 GitHub URL 拼在镜像域名之后）
DEFAULT_MIRRORS = ["https://ghproxy.net/", "https://v4.gh-proxy.org/"]

# 下载体积下限（防止把错误页/半截文件当成安装包）
MIN_ASSET_BYTES = 200 * 1024


# =============================================================================
# 镜像与 URL 工具
# =============================================================================

def normalize_mirrors(raw) -> list[str]:
    """把用户配置（列表/逗号/换行分隔字符串）规整为镜像前缀列表。

    允许用户填 ``ghproxy.net`` / ``https://ghproxy.net`` / ``https://ghproxy.net/``，
    统一补全协议与结尾斜杠。
    """
    if raw is None:
        return list(DEFAULT_MIRRORS)
    if isinstance(raw, str):
        items = re.split(r"[\s,;]+", raw)
    elif isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        return list(DEFAULT_MIRRORS)

    out: list[str] = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        if not re.match(r"^https?://", item, re.I):
            item = "https://" + item
        if not item.endswith("/"):
            item += "/"
        if item not in out:
            out.append(item)
    return out or list(DEFAULT_MIRRORS)


def proxied(url: str, mirrors: list[str]) -> list[str]:
    """返回「直链 + 各镜像代理」的候选列表。"""
    candidates = [url]
    for m in mirrors or []:
        candidates.append(m + url)
    return candidates


def asset_candidates(
    repo: str, asset_name: str, tag: str = "", mirrors: list[str] | None = None
) -> list[str]:
    """构造资产下载链接候选。

    ``tag`` 必须是 Release 的**原始** tag（如 ``v0.3.12``，带 v 前缀），
    否则 releases/download 会 404。空 tag 时用 releases/latest/download
    （GitHub 自动解析到最新版本，是稳定的「更新直链」）。
    """
    mirrors = normalize_mirrors(mirrors)
    if tag:
        base = f"{GITHUB}/{repo}/releases/download/{tag}/{asset_name}"
    else:
        base = f"{GITHUB}/{repo}/releases/latest/download/{asset_name}"
    return proxied(base, mirrors)


# =============================================================================
# HTTP 基础
# =============================================================================

def _get_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(data, dict):
        raise ValueError("响应不是 JSON 对象")
    return data


def _extract_tag_from_url(url: str) -> str:
    m = re.search(r"/releases/tag/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def _normalize_assets(data: dict) -> list[dict]:
    assets = []
    for a in data.get("assets") or []:
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        if name and url:
            assets.append(
                {"name": name, "size": int(a.get("size") or 0), "url": url}
            )
    return assets


def fetch_release(
    repo: str, mirrors: list[str] | None = None, timeout: float = 8.0
) -> dict:
    """获取仓库最新 Release 元信息。

    返回 ``{repo, tag, tag_raw, html_url, assets, via}``；全部通道失败时抛异常。
    ``tag`` 去掉 v 前缀用于版本比较，``tag_raw`` 保留原始 tag 用于拼下载直链。
    ``via`` 说明走的哪条通道：``api`` / ``api-mirror`` / ``redirect``。
    """
    mirrors = normalize_mirrors(mirrors)
    errors: list[str] = []

    # 通道 1/2：API 直连 + 镜像透传 API
    for base in [API] + [m + API for m in mirrors]:
        url = f"{base}/repos/{repo}/releases/latest"
        try:
            data = _get_json(url, timeout=timeout)
            raw_tag = (data.get("tag_name") or "").strip()
            tag = raw_tag.lstrip("v")
            if not tag:
                raise ValueError("缺少 tag_name")
            return {
                "repo": repo,
                "tag": tag,
                "tag_raw": raw_tag,
                "html_url": data.get("html_url") or f"{GITHUB}/{repo}/releases",
                "assets": _normalize_assets(data),
                "via": "api" if base == API else "api-mirror",
            }
        except Exception as exc:  # noqa: BLE001 - 逐通道降级
            errors.append(f"{url} → {exc}")

    # 通道 3：跟随 /releases/latest 的 302 取 tag（无需 API 权限）
    for url in proxied(f"{GITHUB}/{repo}/releases/latest", mirrors):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                final = resp.geturl()
            raw_tag = _extract_tag_from_url(final)
            tag = raw_tag.lstrip("v")
            if not tag:
                raise ValueError("未能从重定向地址解析版本号")
            return {
                "repo": repo,
                "tag": tag,
                "tag_raw": raw_tag,
                "html_url": f"{GITHUB}/{repo}/releases/tag/{raw_tag}",
                "assets": [],
                "via": "redirect",
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url} → {exc}")

    raise RuntimeError("；".join(errors[-3:]) or "无法获取 Release 信息")


# =============================================================================
# 下载
# =============================================================================

def _download_one(url: str, dest: str, progress=None, timeout: float = 30.0) -> int:
    """从单个 URL 下载到 dest，返回字节数。失败抛异常。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream",
        },
    )
    tmp = dest + ".part"
    got = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        total = int(resp.headers.get("Content-Length") or 0)
        # 镜像回源失败时常常直接返回 HTML 错误页
        if "text/html" in ctype:
            raise IOError(f"返回 HTML 页面而非安装包（{ctype}）")
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    if got < 1000:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise IOError(f"文件过小（{got} 字节）")
    os.replace(tmp, dest)
    return got


def _probe_once(url: str, timeout: float = 4.0, sample: int = 65536) -> float | None:
    """用 Range 请求拉一小段，返回耗时秒数；不可用返回 None。"""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/octet-stream",
                "Range": f"bytes=0-{sample - 1}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype:
                return None
            resp.read(sample)
        return time.perf_counter() - t0
    except Exception:  # noqa: BLE001
        return None


def order_by_speed(urls: list[str], timeout: float = 4.0) -> list[str]:
    """并行测速，把可用通道按快慢排序（不可用的排在最后兜底）。"""
    if len(urls) <= 1:
        return list(urls)
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            scores = list(pool.map(lambda u: _probe_once(u, timeout), urls))
    except Exception:  # noqa: BLE001
        return list(urls)
    pairs = [(u, s) for u, s in zip(urls, scores) if s is not None]
    pairs.sort(key=lambda p: p[1])
    bad = [u for u, s in zip(urls, scores) if s is None]
    return [u for u, _ in pairs] + bad


def download(
    urls: list[str],
    dest: str,
    progress=None,
    min_bytes: int = MIN_ASSET_BYTES,
    smart_order: bool = True,
) -> dict:
    """按候选顺序尝试下载，成功返回 {ok, size, url, tried}。

    ``smart_order=True`` 时先并行测速，优先走最快的镜像。
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    ordered = order_by_speed(urls) if smart_order else list(urls)
    tried: list[str] = []
    for url in ordered:
        tried.append(url)
        try:
            size = _download_one(url, dest, progress=progress)
            if size < min_bytes:
                raise IOError(f"文件过小（{size} 字节），可能不是有效安装包")
            return {"ok": True, "size": size, "url": url, "tried": tried}
        except Exception as exc:  # noqa: BLE001 - 换下一个镜像
            tried[-1] = f"{url} → {exc}"
            continue
    return {"ok": False, "error": "所有下载通道均失败", "tried": tried}


# =============================================================================
# 资产挑选
# =============================================================================

def pick_asset(assets: list[dict], kind: str) -> str:
    """从资产列表里挑出目标资产名。kind: ``gui`` / ``cli``。"""
    names = [a.get("name", "") for a in assets if a.get("name")]
    if kind == "gui":
        # 优先 ShieldGUI*.exe，排除安装器/卸载器
        exe = [
            n for n in names
            if n.lower().endswith(".exe")
            and not re.search(r"(setup|install|uninstall|portable)", n, re.I)
        ]
        preferred = [n for n in exe if re.search(r"shield.*gui", n, re.I)]
        if preferred:
            return preferred[0]
        if exe:
            return exe[0]
        # 兜底：发布为 zip 时取第一个 zip
        zips = [
            n for n in names
            if n.lower().endswith(".zip") and not re.search(r"plugin", n, re.I)
        ]
        return zips[0] if zips else ""

    # CLI：优先 shield-windows-amd64.zip，排除 plugin 插件包
    cores = [
        n for n in names
        if "windows" in n.lower()
        and n.lower().endswith(".zip")
        and not re.search(r"plugin", n, re.I)
        and not re.search(r"arm64|aarch64", n, re.I)
    ]
    if not cores:
        cores = [
            n for n in names
            if "windows" in n.lower()
            and n.lower().endswith(".zip")
            and not re.search(r"plugin", n, re.I)
        ]
    if cores:
        exact = [n for n in cores if n.lower() == "shield-windows-amd64.zip"]
        return (exact or cores)[0]
    zips = [
        n for n in names
        if n.lower().endswith(".zip") and not re.search(r"plugin", n, re.I)
    ]
    return zips[0] if zips else ""


def extract_exe(zip_path: str, workdir: str, wanted: str = "shield.exe") -> str:
    """解压 zip 并返回其中的目标 exe 路径（找不到返回空串）。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(workdir)
    direct = os.path.join(workdir, wanted)
    if os.path.isfile(direct):
        return direct
    for root, _dirs, files in os.walk(workdir):
        for f in files:
            if f.lower() == wanted.lower():
                return os.path.join(root, f)
    return ""


# =============================================================================
# 替换与重启
# =============================================================================

def is_frozen() -> bool:
    """是否 PyInstaller 打包运行（决定能否原地替换自身）。"""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> str:
    return os.path.abspath(sys.executable)


def replace_file_with_retry(
    src: str, dst: str, retries: int = 10, delay: float = 0.6, backup: bool = True
) -> dict:
    """用 src 覆盖 dst，带重试（Windows 上运行中的 exe 会被占用）。"""
    if backup and os.path.isfile(dst):
        try:
            shutil.copy2(dst, dst + ".bak")
        except OSError:
            pass  # 备份失败不阻塞更新

    last_err = ""
    for i in range(retries):
        try:
            # 同分区直接原子替换
            os.replace(src, dst)
            return {"ok": True, "attempts": i + 1}
        except OSError as exc:
            last_err = str(exc)
        # 跨分区/权限问题：先复制成 .new 再替换
        try:
            tmp_new = dst + ".new"
            shutil.copy2(src, tmp_new)
            os.replace(tmp_new, dst)
            return {"ok": True, "attempts": i + 1, "method": "copy+replace"}
        except OSError as exc:
            last_err = str(exc)
        if i < retries - 1:
            import time

            time.sleep(delay)
    return {"ok": False, "error": last_err}


# 自替换脚本：纯 ASCII 内容，路径通过参数传入
# （避免 bat 内嵌非 ASCII 路径导致 cmd 按 GBK 解析乱码）
_SELF_REPLACE_BAT = r"""@echo off
setlocal
set "TARGET=%~1"
set "NEW=%~2"
set "PID=%~3"
for /L %%i in (1,1,120) do (
  tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /C:"%PID%" >nul
  if errorlevel 1 goto replace
  timeout /t 1 /nobreak >nul
)
:replace
if exist "%NEW%" move /y "%NEW%" "%TARGET%" >nul 2>&1
start "" "%TARGET%"
del "%~f0"
"""


def schedule_self_replace(new_exe: str, target_exe: str, pid: int | None = None) -> dict:
    """写一个守护 bat，等本进程退出后把新版本覆盖到 target_exe 并启动它。

    返回 ``{ok, bat, error}``；调用方随后应主动退出程序。
    """
    if not IS_WIN:
        return {"ok": False, "error": "自动替换仅支持 Windows"}
    if not os.path.isfile(new_exe):
        return {"ok": False, "error": "新版本文件不存在"}
    pid = pid or os.getpid()
    bat_dir = os.path.join(tempfile.gettempdir(), "shield-gui-update")
    os.makedirs(bat_dir, exist_ok=True)
    bat_path = os.path.join(bat_dir, "self-replace.bat")
    try:
        with open(bat_path, "w", encoding="ascii", newline="\r\n") as f:
            f.write(_SELF_REPLACE_BAT)
        subprocess.Popen(
            ["cmd", "/c", bat_path, target_exe, new_exe, str(pid)],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
            cwd=bat_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "bat": bat_path}
