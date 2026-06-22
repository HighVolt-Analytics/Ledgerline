"""Request-scoped tenant id (ContextVar)."""

from contextvars import ContextVar

_request_tenant_id: ContextVar[int | None] = ContextVar("request_tenant_id", default=None)
_jwt_tenant_id: ContextVar[int | None] = ContextVar("jwt_tenant_id", default=None)


def get_request_tenant_id() -> int | None:
    return _request_tenant_id.get()


def set_request_tenant_id(tenant_id: int | None) -> None:
    _request_tenant_id.set(tenant_id)


def get_jwt_tenant_id() -> int | None:
    return _jwt_tenant_id.get()


def set_jwt_tenant_id(tenant_id: int | None) -> None:
    _jwt_tenant_id.set(tenant_id)


def clear_tenant_context() -> None:
    _request_tenant_id.set(None)
    _jwt_tenant_id.set(None)
