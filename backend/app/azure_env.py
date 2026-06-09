"""Normalize Azure-exported env vars for asyncpg, Celery, and Redis SSL."""

from __future__ import annotations

import ssl
from urllib.parse import quote, unquote, urlparse, urlunparse


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
