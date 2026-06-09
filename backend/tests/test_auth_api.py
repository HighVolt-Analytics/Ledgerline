"""Auth and mailbox API tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth_service import hash_password


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient, db_session: AsyncSession) -> None:
    reg = await client.post(
        "/api/auth/register",
        json={
            "org_name": "Acme Corp",
            "org_slug": "acme-corp",
            "email": "admin@acme.com",
            "password": "securepass1",
            "full_name": "Admin User",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["data"]["access_token"]

    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@acme.com", "password": "securepass1"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["access_token"]

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "admin@acme.com"
    assert me.json()["data"]["org_slug"] == "acme-corp"

    refresh = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refresh.status_code == 200
    assert refresh.json()["data"]["access_token"]
    assert refresh.json()["data"]["user"]["email"] == "admin@acme.com"


@pytest.mark.asyncio
async def test_register_closed_after_first_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        User(
            org_id=1,
            email="existing@test.com",
            password_hash=hash_password("x"),
            full_name="Existing",
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/api/auth/register",
        json={
            "org_name": "Other",
            "org_slug": "other",
            "email": "new@test.com",
            "password": "securepass1",
            "full_name": "New",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_bootstrap_existing_default_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """First admin can attach to default org from test fixtures (hv-org)."""
    reg = await client.post(
        "/api/auth/register",
        json={
            "org_name": "High Volt Analytics",
            "org_slug": "hv-org",
            "email": "admin@hv.com",
            "password": "securepass1",
            "full_name": "Admin User",
        },
    )
    assert reg.status_code == 201
    assert reg.json()["data"]["user"]["org_slug"] == "hv-org"
    assert reg.json()["data"]["user"]["org_name"] == "High Volt Analytics"
