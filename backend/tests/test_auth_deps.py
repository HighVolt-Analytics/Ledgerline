"""Auth context resolves tenant_slug from JWT tenant_id."""

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.deps import _context_from_token
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.membership_service import ensure_membership


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_context_from_token_uses_jwt_tenant_slug(
    db_session: AsyncSession,
) -> None:
    db_session.add(Tenant(id=2, name="Demo Child Co", slug="demo-child"))
    user = User(
        tenant_id=2,
        email="admin@demo.com",
        password_hash=hash_password("x"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=2)

    token = create_access_token(
        user_id=user.id,
        tenant_id=2,
        tenant_slug="demo-child",
        email="admin@demo.com",
        role="admin",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    ctx = await _context_from_token(creds, db_session, _fake_request())

    assert ctx is not None
    assert ctx.tenant_id == 2
    assert ctx.tenant_slug == "demo-child"


@pytest.mark.asyncio
async def test_context_from_token_default_tenant_slug(
    db_session: AsyncSession,
) -> None:
    user = User(
        tenant_id=1,
        email="admin@hv.com",
        password_hash=hash_password("x"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=1)

    token = create_access_token(
        user_id=user.id,
        tenant_id=1,
        tenant_slug="testing",
        email="admin@hv.com",
        role="admin",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    ctx = await _context_from_token(creds, db_session, _fake_request())

    assert ctx is not None
    assert ctx.tenant_slug == "testing"
