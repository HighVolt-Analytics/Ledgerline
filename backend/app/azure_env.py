"""Normalize Azure-exported env vars for asyncpg, Celery, and Redis SSL."""

from __future__ import annotations

import re
import socket
import ssl
import subprocess
import sys
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

_AZURE_POSTGRES_SUFFIX = ".postgres.database.azure.com"
_AZURE_REDIS_SUFFIX = ".redis.cache.windows.net"
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_FALLBACK_DNS = ("8.8.8.8", "1.1.1.1")


def is_ipv4_address(value: str) -> bool:
    token = (value or "").strip()
    if not _IPV4_RE.match(token):
        return False
    try:
        socket.inet_aton(token)
    except OSError:
        return False
    return True


def resolve_host_with_fallback(
    hostname: str,
    *,
    fallback_dns: tuple[str, ...] = _FALLBACK_DNS,
) -> tuple[str, str | None]:
    """Resolve hostname; on DNS failure try public DNS (common on locked-down networks).

    Returns (connect_host, ssl_server_hostname). ssl_server_hostname is set when
    connect_host is an IP but TLS must validate against the original hostname.
    """
    host = (hostname or "").strip()
    if not host or is_ipv4_address(host):
        return host, None

    ip = _resolve_via_system_dns(host)
    if ip:
        return ip, host

    for dns_server in fallback_dns:
        ip = _resolve_via_nslookup(host, dns_server)
        if ip:
            return ip, host

    return host, None


def _resolve_via_system_dns(hostname: str) -> str | None:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    if not infos:
        return None
    return str(infos[0][4][0])


def _resolve_via_nslookup(hostname: str, dns_server: str) -> str | None:
    try:
        proc = subprocess.run(
            ["nslookup", hostname, dns_server],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    candidates: list[str] = []
    for line in (proc.stdout or "").splitlines():
        match = re.search(r"Address:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if not match:
            continue
        ip = match.group(1)
        if ip == dns_server:
            continue
        candidates.append(ip)
    return candidates[-1] if candidates else None


def _needs_azure_dns_fallback(host: object) -> bool:
    token = str(host or "").strip().lower()
    return token.endswith(_AZURE_POSTGRES_SUFFIX) or token.endswith(_AZURE_REDIS_SUFFIX)


def _resolve_with_public_dns(hostname: str) -> str | None:
    for dns_server in _FALLBACK_DNS:
        ip = _resolve_via_nslookup(hostname, dns_server)
        if ip:
            return ip
    return None


_original_getaddrinfo = socket.getaddrinfo
_dns_fallback_installed = False


def install_azure_dns_fallback() -> None:
    """When system DNS blocks Azure, resolve via public DNS before asyncpg/redis connect."""
    global _dns_fallback_installed
    if _dns_fallback_installed:
        return

    def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return _original_getaddrinfo(host, port, family, type, proto, flags)
        except socket.gaierror:
            if not _needs_azure_dns_fallback(host):
                raise
            ip = _resolve_with_public_dns(str(host))
            if not ip:
                raise
            return _original_getaddrinfo(ip, port, family, type, proto, flags)

    socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]
    _dns_fallback_installed = True


def normalize_database_url(url: str) -> str:
    """Convert Azure Postgres URLs to asyncpg form with ssl=require."""
    if not url:
        return url
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    url = url.replace("sslmode=require", "ssl=require")
    url = url.replace("sslmode=prefer", "ssl=prefer")
    return url


def build_postgres_url(
    *,
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> str:
    safe_user = quote(user, safe="")
    safe_password = quote(password, safe="")
    return (
        f"postgresql+asyncpg://{safe_user}:{safe_password}"
        f"@{host}:{port}/{db}?ssl=require"
    )


def build_redis_url(*, host: str, port: int, password: str, db: int) -> str:
    safe_password = quote(password, safe="")
    return f"rediss://:{safe_password}@{host}:{port}/{db}"


def normalize_redis_url(url: str) -> str:
    """Ensure rediss URLs encode passwords that contain @ or =."""
    if not url or not url.startswith("redis"):
        return url
    parsed = urlparse(url)
    if not parsed.hostname:
        return url
    password = unquote(parsed.password or "")
    if not password:
        return url
    safe_password = quote(password, safe="")
    if safe_password == parsed.password:
        return url
    host = parsed.hostname
    port = parsed.port or (6380 if parsed.scheme == "rediss" else 6379)
    netloc = f":{safe_password}@{host}:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def strip_ssl_query_params(url: str) -> str:
    """Remove ssl/sslmode query params when SSL is supplied via connect_args."""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "ssl" not in query and "sslmode" not in query:
        return url
    query.pop("ssl", None)
    query.pop("sslmode", None)
    new_query = urlencode({key: values[0] for key, values in query.items()})
    return urlunparse(parsed._replace(query=new_query))


def asyncpg_connect_args(database_url: str) -> dict[str, Any]:
    """Asyncpg connect_args; Azure Postgres on Windows needs an explicit SSL context."""
    args: dict[str, Any] = {"command_timeout": 60, "timeout": 30}
    if "postgres.database.azure.com" in database_url:
        args["ssl"] = ssl.create_default_context()
    return args


def celery_redis_ssl_options(broker_url: str, backend_url: str) -> dict[str, object]:
    """Celery/kombu SSL options for Azure Cache for Redis (rediss://)."""
    if not broker_url.startswith("rediss://") and not backend_url.startswith("rediss://"):
        return {}
    ssl_opts = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    out: dict[str, object] = {}
    if broker_url.startswith("rediss://"):
        out["broker_use_ssl"] = ssl_opts
    if backend_url.startswith("rediss://"):
        out["redis_backend_use_ssl"] = ssl_opts
    return out
