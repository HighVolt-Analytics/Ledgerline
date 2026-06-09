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
from app.services.org_context import get_org_slug, get_or_create_default_org
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
    org_id: int
    org_slug: str
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
) -> AuthContext | None:
    if not creds or not creds.credentials:
        return None
    payload = decode_access_token(creds.credentials)
    if not payload:
        return None
    org_id = int(payload["org_id"])
    org_slug = str(payload.get("org_slug") or "").strip()
    if not org_slug:
        org_slug = await get_org_slug(db, org_id)
    return AuthContext(
        user_id=int(payload["sub"]),
        org_id=org_id,
        org_slug=org_slug,
        email=str(payload.get("email", "")),
        role=str(payload.get("role", UserRole.MEMBER.value)),
    )


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    ctx = await _context_from_token(creds, db)
    if ctx:
        user = await db.get(User, ctx.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "Session invalid")
        return ctx

    settings = get_settings()
    if not settings.auth_required:
        org = await get_or_create_default_org(db)
        return AuthContext(
            user_id=None,
            org_id=org.id,
            org_slug=org.slug,
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
