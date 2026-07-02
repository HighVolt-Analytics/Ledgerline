"""Auth and mailbox API tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.services.auth_service import hash_password
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import login_via_otp, seed_admin_user


@pytest.mark.asyncio
async def test_register_and_login(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    token = await login_via_otp(
        client,
        db_session,
        email="admin@acme.com",
        tenant_slug="hv-org",
    )

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "admin@acme.com"
    assert me.json()["data"]["tenant_slug"] == "hv-org"

    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@acme.com", "password": "securepass1"},
    )
    challenge = login.json()["data"]["challenge_token"]
    verify = await client.post(
        "/api/auth/verify-otp",
        json={"otp": "123456"},
        headers={"Authorization": f"Bearer {challenge}"},
    )
    refresh_token = verify.json()["data"]["refresh_token"]

    refresh = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh.status_code == 200
    assert refresh.json()["data"]["access_token"]
    assert refresh.json()["data"]["user"]["email"] == "admin@acme.com"

    # Old refresh token remains valid briefly after rotation (multi-tab grace).
    refresh_again = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_again.status_code == 200

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_register_closed_after_first_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        User(
            tenant_id=TESTING_TENANT_UUID,
            email="existing@test.com",
            password_hash=hash_password("x"),
            full_name="Existing",
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/api/auth/register",
        json={
            "tenant_name": "Other",
            "tenant_slug": "other",
            "email": "new@test.com",
            "password": "securepass1",
            "full_name": "New",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_register_bootstrap_existing_default_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """First admin can attach to default org from test fixtures (hv-org)."""
    _, token = await seed_admin_user(
        db_session,
        email="admin@hv.com",
        tenant_slug="hv-org",
        full_name="Admin User",
    )
    await db_session.commit()

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["tenant_slug"] == "hv-org"
    assert me.json()["data"]["tenant_name"] == "High Volt Analytics"
