"""X-Tenant-Id header must match JWT tenant."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User, UserRole
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_header_mismatch_returns_403(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email="header-test@example.com",
        password_hash=hash_password("password123"),
        full_name="Header Test",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=TESTING_TENANT_UUID)

    token = create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        email=user.email,
        role=user.role.value,
    )

    ok = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(TESTING_TENANT_UUID)},
    )
    assert ok.status_code == 200

    bad = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "999"},
    )
    assert bad.status_code == 403

    get_settings.cache_clear()
