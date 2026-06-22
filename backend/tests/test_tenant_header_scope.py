"""X-Tenant-Id header must match JWT tenant."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.membership_service import ensure_membership


@pytest.mark.asyncio
async def test_header_mismatch_returns_403(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = User(
        tenant_id=1,
        email="header-test@example.com",
        password_hash=hash_password("password123"),
        full_name="Header Test",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=1)

    token = create_access_token(
        user_id=user.id,
        tenant_id=1,
        tenant_slug="testing",
        email=user.email,
        role=user.role.value,
    )

    ok = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "1"},
    )
    assert ok.status_code == 200

    bad = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "999"},
    )
    assert bad.status_code == 403

    get_settings.cache_clear()
