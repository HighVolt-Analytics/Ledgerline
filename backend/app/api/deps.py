import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.common import ApiEnvelope, ErrorDetail, ResponseMeta
from app.services.auth_service import decode_access_token
from app.services.membership_service import get_membership_role, user_has_tenant_access
from app.services.tenant_context_service import get_or_create_default_tenant, get_tenant_slug
from app.tenant_context import set_jwt_tenant_id, set_request_tenant_id
from app.tenant_isolation.resolution import TenantResolutionService
from app.tenant_rls import apply_rls_session_context
from app.tenant_status import assert_tenant_active_for_user
from app.utils.logger import correlation_id_ctx

__all__ = [
    "ApiEnvelope",
    "AuthContext",
    "CorrelationIdMiddleware",
    "ErrorDetail",
    "ResponseMeta",
    "get_auth_context",
    "get_db",
    "require_admin",
    "require_user",
]

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: int | None
    tenant_id: int
    tenant_slug: str
    email: str
    role: str


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_ctx.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)


async def _context_from_token(
    creds: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
    request: Request,
) -> AuthContext | None:
    if not creds or not creds.credentials:
        return None
    payload = decode_access_token(creds.credentials)
    if not payload:
        return None

    tenant_id = int(payload.get("tenant_id") or payload.get("org_id", 0))
    if tenant_id <= 0:
        return None

    tenant_slug = str(payload.get("tenant_slug") or payload.get("org_slug") or "").strip()
    if not tenant_slug:
        tenant_slug = await get_tenant_slug(db, tenant_id)

    set_jwt_tenant_id(tenant_id)
    set_request_tenant_id(tenant_id)

    x_tid = request.headers.get("X-Tenant-Id")
    err = TenantResolutionService.validate_header_scope(tenant_id, x_tid)
    if err:
        raise HTTPException(403, err)

    role = str(payload.get("role", UserRole.MEMBER.value))
    user_id = int(payload["sub"])

    if not await user_has_tenant_access(db, user_id=user_id, tenant_id=tenant_id):
        raise HTTPException(403, "Tenant access denied")

    membership_role = await get_membership_role(db, user_id=user_id, tenant_id=tenant_id)
    if membership_role:
        role = membership_role

    return AuthContext(
        user_id=user_id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        email=str(payload.get("email", "")),
        role=role,
    )


async def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    ctx = await _context_from_token(creds, db, request)
    if ctx:
        user = await db.get(User, ctx.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "Session invalid")
        set_request_tenant_id(ctx.tenant_id)
        await apply_rls_session_context(db, ctx.tenant_id)
        await assert_tenant_active_for_user(db, user)
        return ctx

    settings = get_settings()
    if not settings.auth_required:
        tenant = await get_or_create_default_tenant(db)
        set_request_tenant_id(tenant.id)
        await apply_rls_session_context(db, tenant.id)
        return AuthContext(
            user_id=None,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            email="system@local",
            role=UserRole.ADMIN.value,
        )

    raise HTTPException(401, "Authentication required")


async def get_auth_context(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if ctx.role != UserRole.ADMIN.value:
        raise HTTPException(403, "Admin access required")
    return ctx


async def actor_from_context(db: AsyncSession, ctx: AuthContext) -> tuple[str, str]:
    """Return (display_name, email) for audit attribution."""
    if ctx.user_id:
        user = await db.get(User, ctx.user_id)
        if user:
            return user.full_name, user.email
    if ctx.email:
        return ctx.email.split("@")[0].replace(".", " ").title(), ctx.email
    return "System", "system@local"
