"""网络连通性预检 + Shield CLI 启动错误诊断。

背景：`shield <proto>` 启动时会向控制台 `POST /api/public/quick-setup`，
网络不通时 Go 客户端会重试若干次后报
``context deadline exceeded (Client.Timeout exceeded while awaiting headers)``，
GUI 原先只把这段英文丢进日志，且进程已经退出仍显示「运行中」。

本模块提供：
- ``probe()``      —— 启动前分阶段探测 DNS / TCP / TLS / HTTP，给出中文诊断
- ``diagnose_log`` —— 从 CLI 输出识别错误模式，转成结构化中文说明
- ``proxy_env()``  —— 构造传给 CLI 子进程的代理环境变量（Go 标准库支持）
"""
from __future__ import annotations

import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SERVER = "https://console.yishield.com/raas"
# 只读、无副作用的探测路径（不会真的创建隧道）
PROBE_PATH = "/api/version/latest"
USER_AGENT = "ShieldGUI-NetProbe/1.0"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def normalize_server(raw: str = "") -> str:
    """规范化服务器地址：补 https、去掉尾斜杠与重复的 /raas。"""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return DEFAULT_SERVER
    if "://" not in url:
        url = "https://" + url
    return url


def proxy_env(proxy: str = "") -> dict:
    """返回需要合并进子进程环境的代理变量。

    显式配置时覆盖系统值；留空时返回空字典（沿用系统/环境变量）。
    Go 的 net/http 默认 ProxyFromEnvironment，会读这些变量。
    """
    p = (proxy or "").strip()
    if not p:
        return {}
    if "://" not in p:
        p = "http://" + p
    vars_ = {
        "HTTP_PROXY": p, "http_proxy": p,
        "HTTPS_PROXY": p, "https_proxy": p,
    }
    # 本地回环与 Web 面板不走代理，避免 127.0.0.1 请求被代理吞掉
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = [x.strip() for x in no_proxy.split(",") if x.strip()]
    for item in ("localhost", "127.0.0.1", "::1"):
        if item not in parts:
            parts.append(item)
    vars_["NO_PROXY"] = ",".join(parts)
    vars_["no_proxy"] = vars_["NO_PROXY"]
    return vars_


def effective_proxy(proxy: str = "") -> str:
    """预检时实际使用的代理：显式配置 > 环境变量 > 系统代理。"""
    p = (proxy or "").strip()
    if p:
        return p if "://" in p else "http://" + p
    env = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
    )
    if env:
        return env
    try:
        sysp = urllib.request.getproxies()
        return sysp.get("https") or sysp.get("http") or ""
    except Exception:  # noqa: BLE001
        return ""


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ---------------------------------------------------------------------------
# 分阶段探测
# ---------------------------------------------------------------------------

def _probe_direct(host: str, port: int, timeout: float) -> dict:
    """裸链路分阶段探测（不经代理）：DNS → TCP → TLS。"""
    out = {"dns_ms": None, "connect_ms": None, "tls_ms": None, "ip": ""}
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        out["ip"] = infos[0][4][0] if infos else ""
    except Exception as exc:  # noqa: BLE001
        out["dns_ms"] = _ms(t0)
        out.update(stage="dns", detail=str(exc))
        return out
    out["dns_ms"] = _ms(t0)

    sock = None
    t1 = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
    except Exception as exc:  # noqa: BLE001
        out["connect_ms"] = _ms(t1)
        out.update(stage="connect", detail=str(exc))
        return out
    out["connect_ms"] = _ms(t1)

    t2 = time.perf_counter()
    try:
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
    except Exception as exc:  # noqa: BLE001
        out["tls_ms"] = _ms(t2)
        out.update(stage="tls", detail=str(exc))
        try:
            sock.close()
        except Exception:
            pass
        return out
    out["tls_ms"] = _ms(t2)
    try:
        sock.close()
    except Exception:
        pass
    out["stage"] = "tls_ok"
    return out


def _probe_http(server: str, proxy: str, timeout: float) -> dict:
    """真实 HTTP 请求探测（走与 CLI 一致的代理配置），任何 HTTP 状态码都算「通」。"""
    url = server.rstrip("/") + PROBE_PATH
    t0 = time.perf_counter()
    handler = (
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        if proxy else urllib.request.ProxyHandler()
    )
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, method="GET"
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return {"ok": True, "code": resp.status, "ms": _ms(t0), "stage": "done"}
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 也说明链路通、服务端有响应
        return {"ok": True, "code": exc.code, "ms": _ms(t0), "stage": "done"}
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        reason = getattr(exc, "reason", None)
        if reason is not None:
            detail = f"{exc}（{reason}）"
        low = detail.lower()
        stage = "http_timeout" if (
            "timed out" in low or "timeout" in low or "deadline" in low
        ) else "http"
        return {"ok": False, "code": None, "ms": _ms(t0),
                "stage": stage, "detail": detail}


_STAGE_LABEL = {
    "dns": "DNS 解析",
    "connect": "TCP 连接",
    "tls": "TLS 握手",
    "http": "HTTP 请求",
    "http_timeout": "等待响应头",
    "done": "完成",
}

_ADVICE = {
    "dns": [
        "检查 DNS 设置，可临时改用 114.114.114.114 / 223.5.5.5 后重试",
        "若使用代理，确认代理地址填写正确（形如 http://127.0.0.1:7890）",
    ],
    "connect": [
        "检查本机网络与防火墙，确认 443 端口出方向未被拦截",
        "国内链路到该域名不稳定时，可在下方配置可用的 HTTP 代理",
        "稍后重试；CLI 内部会自动重试 5 次 quick-setup 请求",
    ],
    "tls": [
        "确认系统时间正确（证书校验依赖系统时钟）",
        "若公司网络有 HTTPS 中间人设备，需安装其根证书或改用代理",
    ],
    "http_timeout": [
        "控制台接口在等待响应头时超时：链路丢包、服务端负载高或代理失效",
        "检查代理软件是否已启动；失效的系统代理会让请求一直挂起",
        "可在「应用配置 → 网络与连接」里指定代理，或临时关闭预检直接启动",
        "稍后重试，CLI 会自动重试 5 次，GUI 也可配置自动重试",
    ],
    "http": [
        "检查代理配置是否正确，或临时关闭代理后重试",
        "确认服务器地址完整（默认 https://console.yishield.com/raas）",
    ],
    "server_error": [
        "服务端已响应但返回错误，属于服务端临时故障，稍后重试即可",
        "若持续出现，可切换到自定义服务器地址",
    ],
}


def probe(server: str = "", proxy: str = "", timeout: float = 3.0) -> dict:
    """探测控制台可达性，返回结构化中文诊断。

    以「真实 HTTP 请求能否收到响应头」为 ``ok`` 判据；裸链路分阶段结果
    仅作为排查细节（走代理时跳过直连分阶段，避免误导）。
    """
    srv = normalize_server(server)
    parts = urllib.parse.urlsplit(srv)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    use_proxy = effective_proxy(proxy)
    t0 = time.perf_counter()

    result: dict = {
        "ok": False, "server": srv, "proxy": use_proxy,
        "via": "proxy" if use_proxy else "direct",
        "stage": "", "stage_label": "", "message": "", "advice": [],
        "detail": "", "http_code": None, "elapsed_ms": 0,
        "dns_ms": None, "connect_ms": None, "tls_ms": None,
        "http_ms": None, "ip": "",
    }

    if not use_proxy:
        direct = _probe_direct(host, port, timeout)
        result.update({k: direct.get(k) for k in
                       ("dns_ms", "connect_ms", "tls_ms", "ip")})
        # 裸链路某阶段就失败：直接给出结论，不必再发 HTTP 请求
        if direct.get("stage") in ("dns", "connect", "tls"):
            stage = direct["stage"]
            result.update(
                stage=stage, stage_label=_STAGE_LABEL[stage],
                detail=direct.get("detail", ""),
                message=f"{_STAGE_LABEL[stage]}失败，控制台无法访问",
                advice=_ADVICE[stage], elapsed_ms=_ms(t0),
            )
            return result

    http = _probe_http(srv, use_proxy, timeout)
    result["http_ms"] = http.get("ms")
    result["elapsed_ms"] = _ms(t0)
    result["http_code"] = http.get("code")

    if http.get("ok"):
        code = http.get("code") or 0
        result["stage"] = "done"
        result["stage_label"] = "完成"
        result["ok"] = True
        if code >= 500:
            result["message"] = f"网络可达，但服务端返回 HTTP {code}（临时故障）"
            result["advice"] = _ADVICE["server_error"]
        else:
            result["message"] = f"网络可达（HTTP {code}）"
        return result

    stage = http.get("stage", "http")
    label = _STAGE_LABEL.get(stage, "HTTP 请求")
    result.update(
        stage=stage, stage_label=label,
        detail=http.get("detail", ""),
        message=f"{label}失败，控制台无响应（{http.get('ms', 0)} ms）",
        advice=_ADVICE.get(stage, _ADVICE["http"]),
    )
    return result


# ---------------------------------------------------------------------------
# CLI 输出诊断
# ---------------------------------------------------------------------------

# (错误码, 正则, 标题, 原因, 建议, 是否可自动重试)
_PATTERNS: list[tuple[str, str, str, str, list[str], bool]] = [
    (
        "quota", r"Maximum 10 applications|10 applications allowed",
        "应用数量已达服务端上限",
        "控制台账号下已有 10 个应用，quick-setup 无法再创建新的隧道。",
        ["到控制台或 Web 面板删除不用的应用", "清理「活动会话」里失效的条目"],
        False,
    ),
    (
        "timeout",
        r"context deadline exceeded|Client\.Timeout exceeded while awaiting headers"
        r"|Connection timed out|i/o timeout",
        "控制台接口响应超时",
        "quick-setup 请求已发出，但在等待响应头时超时：链路丢包、服务端繁忙，"
        "或系统代理已失效导致请求一直挂起。",
        ["检查网络与代理软件是否正常运行", "在「应用配置 → 网络与连接」中指定可用代理",
         "稍后重试；CLI 内部会自动重试 5 次", "若使用私有服务端，确认 --server 地址正确"],
        True,
    ),
    (
        "server_error", r"Bad Gateway|Service Unavailable|HTTP 5\d\d|\b(502|503|504)\b",
        "控制台服务暂时不可用",
        "链路已通，但网关或服务端返回错误，通常是临时故障或正在维护。",
        ["稍后重试（可开启自动重试）", "持续出现时检查控制台状态或换自定义服务器"],
        True,
    ),
    (
        "dns", r"DNS resolution failed|no such host|lookup .*no such host"
        r"|dial tcp: lookup|getaddrinfo",
        "域名解析失败",
        "无法把控制台域名解析为 IP，通常是 DNS 配置异常或网络未连通。",
        ["检查网络连接与 DNS（可改用 114.114.114.114 / 223.5.5.5）",
         "确认 --server 里的域名拼写正确"],
        False,
    ),
    (
        "refused", r"connection refused|No connection could be made|connectex",
        "连接被拒绝",
        "目标服务器主动拒绝了连接，可能是端口不对、服务未启动或防火墙拦截。",
        ["确认服务器地址与端口", "检查本机防火墙/安全软件"],
        False,
    ),
    (
        "tls", r"certificate|x509|TLS handshake|tls: ",
        "TLS 证书校验失败",
        "HTTPS 握手或证书校验未通过，常见于系统时间错误或网络中的 HTTPS 中间人设备。",
        ["校准系统时间", "公司网络需安装对应根证书", "检查代理是否做了 HTTPS 解密"],
        False,
    ),
    (
        "auth", r"Authentication failed|invalid token|unauthorized|\b(401|403)\b"
        r"|failed to load credentials|credentials",
        "凭证或权限校验失败",
        "服务端拒绝了本次请求，可能是本地缓存的凭证失效或账号权限不足。",
        ["到「凭证与安全」或「缓存管理」清除本地凭证缓存后重新连接",
         "确认控制台账号状态"],
        False,
    ),
    (
        "bad_param", r"Invalid request body|protocol is required|API error \(code=",
        "请求参数被服务端拒绝",
        "quick-setup 的参数不被服务端接受，常见于协议名/目标地址不合法或版本不匹配。",
        ["检查协议与目标地址", "把 Shield CLI 更新到最新版后重试"],
        False,
    ),
    (
        "generic", r"Connection failed|Quick-setup API failed|Quick-setup API error"
        r"|Quick-setup HTTP failed|Connection error|failed to connect",
        "隧道建立失败",
        "CLI 在完成 quick-setup 前退出，未能与控制台建立隧道。",
        ["查看下方原始日志定位具体原因", "检查网络与代理后重试"],
        True,
    ),
]

_FATAL_RE = re.compile(
    r"Connection failed|Quick-setup API (?:failed|error)|Quick-setup HTTP failed"
    r"|Please check your network|Connection error:|✗",
    re.IGNORECASE,
)
_RETRY_RE = re.compile(r"attempt\s+(\d+)\s*/\s*(\d+)\s+failed", re.IGNORECASE)


def is_fatal_line(line: str) -> bool:
    """CLI 明确宣告最终失败的行（区别于内部重试日志）。"""
    return bool(_FATAL_RE.search(line or ""))


def parse_retry_attempt(line: str) -> tuple[int, int] | None:
    """解析 ``attempt 1/5 failed``，返回 (当前次数, 总次数)。"""
    m = _RETRY_RE.search(line or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def diagnose_log(text: str) -> dict | None:
    """把 CLI 输出（可含多行）诊断成结构化中文说明。

    按行倒序匹配，优先采用最后出现的错误（CLI 最终失败行通常在末尾），
    避免把多行日志拼成一段难以阅读的「原始错误」。
    """
    if not text:
        return None
    lines = [ln.strip() for ln in text[-6000:].splitlines() if ln.strip()]
    for code, pattern, title, reason, advice, retryable in _PATTERNS:
        for line in reversed(lines):
            m = re.search(pattern, line, re.IGNORECASE)
            if not m:
                continue
            raw = line[max(0, m.start() - 40): m.end() + 160].strip()
            return {
                "code": code, "title": title, "reason": reason,
                "advice": list(advice), "retryable": retryable,
                "raw": raw[:300],
            }
    return None


def format_diagnosis(diag: dict) -> str:
    """生成写进会话日志的中文诊断块。"""
    lines = [
        "", "────────────────────────────────────────────",
        f"[Shield GUI 诊断] {diag.get('title', '启动失败')}",
        f"原因：{diag.get('reason', '—')}",
        "建议：",
    ]
    lines += [f"  {i}. {a}" for i, a in enumerate(diag.get("advice", []), 1)]
    if diag.get("raw"):
        lines.append(f"原始错误：{diag['raw']}")
    lines.append("────────────────────────────────────────────")
    return "\n".join(lines) + "\n"
