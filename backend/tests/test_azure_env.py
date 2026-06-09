"""Azure env URL normalization helpers."""

from app.azure_env import (
    build_postgres_url,
    build_redis_url,
    celery_redis_ssl_options,
    normalize_database_url,
    normalize_redis_url,
)


def test_normalize_database_url_asyncpg_ssl() -> None:
    raw = (
        "postgresql://pgadmin:secret@pg-emailacct-49964.postgres.database.azure.com"
        ":5432/email_accounting?sslmode=require"
    )
    out = normalize_database_url(raw)
    assert out.startswith("postgresql+asyncpg://")
    assert "ssl=require" in out
    assert "sslmode=" not in out


def test_build_postgres_url_encodes_password() -> None:
    url = build_postgres_url(
        host="pg-emailacct-49964.postgres.database.azure.com",
        port=5432,
        db="email_accounting",
        user="pgadmin",
        password="p@ss:word",
    )
    assert "postgresql+asyncpg://" in url
    assert "p%40ss%3Aword" in url
    assert "ssl=require" in url


def test_build_redis_url_encodes_trailing_equals() -> None:
    url = build_redis_url(
        host="redis-emailacct-49964.redis.cache.windows.net",
        port=6380,
        password="abc123=",
        db=0,
    )
    assert url.startswith("rediss://:")
    assert "abc123%3D" in url
    assert url.endswith("/0")


def test_normalize_redis_url_reencodes_password() -> None:
    raw = "rediss://:abc123=@redis-emailacct-49964.redis.cache.windows.net:6380/0"
    out = normalize_redis_url(raw)
    assert "abc123%3D" in out


def test_celery_redis_ssl_options_for_rediss() -> None:
    opts = celery_redis_ssl_options(
        "rediss://:x@host:6380/0",
        "rediss://:x@host:6380/1",
    )
    assert "broker_use_ssl" in opts
    assert "redis_backend_use_ssl" in opts


def test_celery_redis_ssl_options_skips_plain_redis() -> None:
    assert celery_redis_ssl_options("redis://localhost:6379/0", "redis://localhost:6379/1") == {}
