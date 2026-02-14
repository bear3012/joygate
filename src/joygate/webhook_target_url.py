"""
Webhook target_url 校验：单点复用，订阅创建与投递前均调用。
禁止内网/保留网段、userinfo、非 http(s) scheme；可选允许 http 与 localhost（本地 demo）。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# 长度上限（与 config.WEBHOOK_TARGET_URL_MAX_LEN 一致，此处避免循环依赖）
TARGET_URL_MAX_LEN = 2048


def _is_blocked_ip(ip_str: str, allow_localhost: bool) -> bool:
    """判断 IP 是否在禁止范围内（内网/保留/元数据等）。allow_localhost 时放行 127.0.0.0/8 与 ::1。"""
    ip_str = ip_str.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_loopback:
        return not allow_localhost
    if addr.is_private:
        return True
    if addr.is_link_local:
        return True
    if addr.is_reserved:
        return True
    if addr.is_multicast:
        return True
    if addr.is_unspecified:
        return True
    # 100.64.0.0/10 (RFC 6598)
    if isinstance(addr, ipaddress.IPv4Address):
        n = int(addr)
        if 0x64400000 <= n <= 0x647FFFFF:
            return True
    return False


def validate_webhook_target_url(
    target_url: str,
    allow_http: bool = False,
    allow_localhost: bool = False,
) -> tuple[bool, str | None]:
    """
    统一校验 target_url。返回 (ok, last_error)。
    ok=True 时 last_error 为 None；ok=False 时 last_error 为 invalid_target_url（delivery 用，不暴露细节）。
    """
    if not isinstance(target_url, str):
        return False, "invalid_target_url"
    s = target_url.strip()
    if not s:
        return False, "invalid_target_url"
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        return False, "invalid_target_url"
    if "\\" in s:
        return False, "invalid_target_url"
    if len(s) > TARGET_URL_MAX_LEN:
        return False, "invalid_target_url"

    try:
        parsed = urlparse(s)
    except Exception:
        return False, "invalid_target_url"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("https", "http"):
        return False, "invalid_target_url"
    if scheme == "http" and not allow_http:
        return False, "invalid_target_url"

    if not parsed.netloc:
        return False, "invalid_target_url"
    if parsed.username is not None or parsed.password is not None:
        return False, "invalid_target_url"
    if "@" in parsed.netloc:
        return False, "invalid_target_url"

    host = parsed.hostname
    if not host:
        return False, "invalid_target_url"

    host_lower = host.lower()
    if host_lower in ("0.0.0.0", "169.254.169.254"):
        return False, "invalid_target_url"

    try:
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80
    except ValueError:
        return False, "invalid_target_url"

    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "invalid_target_url"
    except Exception:
        return False, "invalid_target_url"

    for (_family, _type, _proto, _canon, sockaddr) in infos:
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str, allow_localhost):
            return False, "invalid_target_url"

    return True, None
