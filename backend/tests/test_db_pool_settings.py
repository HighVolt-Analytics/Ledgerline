"""DB pool sizing for shared Azure Flexible Server."""

from __future__ import annotations

from app.config import Settings


def test_db_pool_defaults_are_conservative() -> None:
    s = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    assert s.db_pool_size == 5
    assert s.db_max_overflow == 5
    assert s.db_pool_timeout_seconds == 20


def test_db_pool_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "15")
    s = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    assert s.db_pool_size == 3
    assert s.db_max_overflow == 2
    assert s.db_pool_timeout_seconds == 15


def test_mailbox_poll_concurrency_default_reduced() -> None:
    s = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    assert s.mailbox_poll_concurrency == 2
