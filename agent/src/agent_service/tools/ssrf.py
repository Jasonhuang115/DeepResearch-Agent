from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.internal",
        "metadata",
    }
)

# Clash / Surge / Mihomo fake-ip (RFC 2544). System DNS returns these
# instead of the real A record; the proxy then maps them outbound.
# They are reserved, so ip.is_global is False, but they are not LAN
# or cloud metadata. Allow them only as resolved names, not as URL hosts.
_FAKE_IP_NETS = (ipaddress.ip_network("198.18.0.0/15"),)


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _as_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    ip = ipaddress.ip_address(raw)
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def is_fake_ip(raw: str) -> bool:
    ip = _as_ip(raw)
    return any(ip in net for net in _FAKE_IP_NETS)


def is_public_ip(raw: str) -> bool:
    return bool(_as_ip(raw).is_global)


def is_allowed_resolved_ip(raw: str) -> bool:
    return is_public_ip(raw) or is_fake_ip(raw)


def blocked_reason(url: str, *, resolved_ips: list[str] | None = None) -> str | None:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return "only http/https URLs are allowed"
    host = (parsed.hostname or "").lower()
    if not host:
        return "url host is required"
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        return f"blocked host: {host}"
    if is_ip_literal(host) and not is_public_ip(host):
        return f"blocked address: {host}"
    if resolved_ips is not None:
        for raw in resolved_ips:
            if not is_allowed_resolved_ip(raw):
                return f"blocked address: {raw}"
    return None


async def resolve_host(host: str) -> list[str]:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    out: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out
