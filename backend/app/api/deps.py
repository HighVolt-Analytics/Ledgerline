import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.database import get_db, get_preauth_db
from app.models.user import User, UserRole, SUPER_ADMIN_ROLE
from app.models.tenant import Tenant
from app.tenant_roles import TenantRole
from app.schemas.common import ApiEnvelope, ErrorDetail, ResponseMeta
from app.services.auth.auth_service import decode_access_token
from app.services.auth.membership_service import resolve_auth_principals
from app.services.tenant.tenant_context_service import get_tenant_slug
from app.tenant_context import set_jwt_tenant_id, set_request_tenant_id
from app.tenant_isolation.resolution import TenantResolutionService
from app.tenant_rls import apply_platform_lookup_session, apply_rls_session_context
from app.tenant_ids import parse_tenant_id
from app.tenant_status import assert_tenant_active
from app.utils.logger import correlation_id_ctx, get_logger

logger = get_logger(__name__)

__all__ = [
    "ApiEnvelope",
    "AuthContext",
    "CorrelationIdMiddleware",
    "bind_db_to_tenant",
    "cross_tenant_db_lookup",
    "ErrorDetail",
    "ResponseMeta",
    "get_auth_context",
    "get_db",
    "get_preauth_db",
    "require_admin",
    "require_super_admin",
    "is_super_admin_role",
    "require_user",
]

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: int | None
    tenant_id: uuid.UUID
    tenant_slug: str
    email: str
    role: str
    is_support_session: bool = False
    user: User | None = None
    tenant: Tenant | None = None


class CorrelationIdMiddleware:
    """Pure ASGI middleware — avoids Starlette BaseHTTPMiddleware deadlocks under load."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cid = headers.get("x-correlation-id") or str(uuid.uuid4())
        token = correlation_id_ctx.set(cid)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-correlation-id", cid.encode("latin-1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
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

    tenant_id = parse_tenant_id(payload.get("tenant_id") or payload.get("org_id"))
    if tenant_id is None:
        logger.warning(
            "auth_missing_tenant_in_jwt",
            user_id=payload.get("sub"),
            path=request.url.path,
        )
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

    principals = await resolve_auth_principals(
        db, user_id=user_id, tenant_id=tenant_id
    )
    if not principals:
        raise HTTPException(403, "Tenant access denied")

    role = principals.role or role
    await assert_tenant_active(principals.tenant)

    return AuthContext(
        user_id=user_id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        email=str(payload.get("email", "")),
        role=role,
        is_support_session=bool(payload.get("is_support_session")),
        user=principals.user,
        tenant=principals.tenant,
    )


async def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    ctx = await _context_from_token(creds, db, request)
    if ctx:
        if ctx.is_support_session:
            raise HTTPException(
                403,
                "Support workspace access is disabled for organisation data security",
            )
        set_request_tenant_id(ctx.tenant_id)
        await apply_rls_session_context(db, ctx.tenant_id)
        logger.debug(
            "auth_context_resolved",
            tenant_id=str(ctx.tenant_id),
            user_id=ctx.user_id,
            role=ctx.role,
            path=request.url.path,
            x_tenant_id=request.headers.get("X-Tenant-Id"),
        )
        return ctx

    # Never impersonate a default org — tenant APIs always require a valid JWT.
    if creds and creds.credentials:
        raise HTTPException(401, "Invalid or expired token")
    raise HTTPException(401, "Authentication required")


async def get_auth_context(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if is_super_admin_role(ctx.role):
        raise HTTPException(403, "Tenant admin access required")
    if ctx.role != TenantRole.ADMIN.value and ctx.role != UserRole.ADMIN.value:
        raise HTTPException(403, "Admin access required")
    return ctx


def is_super_admin_role(role: str) -> bool:
    return role == SUPER_ADMIN_ROLE


async def require_super_admin(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if not is_super_admin_role(ctx.role):
        raise HTTPException(403, "Super admin access required")
    return ctx


async def bind_db_to_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set request + PostgreSQL RLS for unauthenticated tenant-scoped handlers."""
    set_request_tenant_id(tenant_id)
    await apply_rls_session_context(db, tenant_id)


async def actor_from_context(db: AsyncSession, ctx: AuthContext) -> tuple[str, str]:
    """Return (display_name, email) for audit attribution."""
    if ctx.user:
        return ctx.user.full_name, ctx.user.email
    if ctx.user_id:
        user = await db.get(User, ctx.user_id)
        if user:
            return user.full_name, user.email
    if ctx.email:
        return ctx.email.split("@")[0].replace(".", " ").title(), ctx.email
    return "System", "system@local"


@asynccontextmanager
async def cross_tenant_db_lookup(
    db: AsyncSession,
    *,
    restore_tenant_id: uuid.UUID | None = None,
):
    """Temporarily disable RLS to enumerate memberships, then restore tenant scope."""
    await apply_platform_lookup_session(db)
    try:
        yield db
    finally:
        from app.tenant_rls import clear_platform_lookup_session

        await clear_platform_lookup_session(db)
        if restore_tenant_id is not None:
            await apply_rls_session_context(db, restore_tenant_id)
