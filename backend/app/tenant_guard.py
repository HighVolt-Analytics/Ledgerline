"""Fail-fast when tenant context is required but missing."""

from fastapi import HTTPException

from app.tenant_context import get_request_tenant_id


class TenantContextError(HTTPException):
    def __init__(self, detail: str = "Tenant context required") -> None:
        super().__init__(status_code=400, detail=detail)


def require_tenant_id() -> int:
    tid = get_request_tenant_id()
    if tid is None:
        raise TenantContextError()
    return tid
