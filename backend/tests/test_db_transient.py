"""Transient PostgreSQL connection error detection."""

from sqlalchemy.exc import DBAPIError

from app.db_transient import is_transient_connection_error


class _FakeConnectionDoesNotExistError(Exception):
    pass


def test_is_transient_connection_error_detects_asyncpg_name() -> None:
    err = _FakeConnectionDoesNotExistError("connection was closed in the middle of operation")
    err.__class__.__name__ = "ConnectionDoesNotExistError"
    wrapped = DBAPIError("SELECT 1", {}, err)
    assert is_transient_connection_error(wrapped)


def test_is_transient_connection_error_ignores_logic_errors() -> None:
    assert not is_transient_connection_error(ValueError("bad data"))
