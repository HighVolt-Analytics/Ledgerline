"""Auth context resolves org_slug from JWT org_id."""

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import _context_from_token
from app.models.organisation import Organisation
from app.services.auth_service import create_access_token


@pytest.mark.asyncio
async def test_context_from_token_uses_jwt_org_slug(
    db_session: AsyncSession,
) -> None:
    db_session.add(Organisation(id=2, name="Demo Child Co", slug="demo-child"))
    await db_session.flush()

    token = create_access_token(
        user_id=1,
        org_id=2,
        org_slug="demo-child",
        email="admin@demo.com",
        role="admin",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    ctx = await _context_from_token(creds, db_session)

    assert ctx is not None
    assert ctx.org_id == 2
    assert ctx.org_slug == "demo-child"


@pytest.mark.asyncio
async def test_context_from_token_default_org_hv_slug(
    db_session: AsyncSession,
) -> None:
    token = create_access_token(
        user_id=1,
        org_id=1,
        org_slug="hv-org",
        email="admin@hv.com",
        role="admin",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    ctx = await _context_from_token(creds, db_session)

    assert ctx is not None
    assert ctx.org_slug == "hv-org"
