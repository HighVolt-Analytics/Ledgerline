"""Tenant members list, invite, role change, and accept flow."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


async def _seed_user(
    db_session: AsyncSession,
    *,
    email: str,
    role: str,
    full_name: str,
) -> User:
    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email=email,
        password_hash=hash_password("password123"),
        full_name=full_name,
        role=UserRole.ADMIN if role == "admin" else UserRole.MEMBER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=TESTING_TENANT_UUID, role=role)
    await db_session.commit()
    return user


def _token_for(user: User, *, role: str) -> str:
    return create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=user.email,
        role=role,
    )


@pytest.mark.asyncio
async def test_admin_lists_and_invites_member(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    admin = await _seed_user(
        db_session,
        email="admin-members@test.com",
        role="admin",
        full_name="Admin User",
    )
    headers = {"Authorization": f"Bearer {_token_for(admin, role='admin')}"}

    listed = await client.get("/api/tenants/current/members", headers=headers)
    assert listed.status_code == 200
    body = listed.json()["data"]
    assert any(m["email"] == admin.email for m in body["members"])

    invited = await client.post(
        "/api/tenants/current/members/invite",
        headers=headers,
        json={
            "email": "new-hire@test.com",
            "full_name": "New Hire",
            "role": "bookkeeper",
        },
    )
    assert invited.status_code == 200
    assert "accept-invite" in invited.json()["data"]["accept_url"]

    listed2 = await client.get("/api/tenants/current/members", headers=headers)
    pending = listed2.json()["data"]["pending_invites"]
    assert any(p["email"] == "new-hire@test.com" for p in pending)

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_revokes_pending_invite(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    admin = await _seed_user(
        db_session,
        email="revoke-admin@test.com",
        role="admin",
        full_name="Revoke Admin",
    )
    headers = {"Authorization": f"Bearer {_token_for(admin, role='admin')}"}

    invited = await client.post(
        "/api/tenants/current/members/invite",
        headers=headers,
        json={
            "email": "revoke-me@test.com",
            "full_name": "Revoke Me",
            "role": "viewer",
        },
    )
    assert invited.status_code == 200
    invite_id = invited.json()["data"]["invite_id"]

    revoked = await client.delete(
        f"/api/tenants/current/members/invites/{invite_id}",
        headers=headers,
    )
    assert revoked.status_code == 200

    listed = await client.get("/api/tenants/current/members", headers=headers)
    pending = listed.json()["data"]["pending_invites"]
    assert not any(p["email"] == "revoke-me@test.com" for p in pending)

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_viewer_cannot_invite(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    viewer = await _seed_user(
        db_session,
        email="viewer-members@test.com",
        role="viewer",
        full_name="Viewer User",
    )
    headers = {"Authorization": f"Bearer {_token_for(viewer, role='viewer')}"}

    res = await client.post(
        "/api/tenants/current/members/invite",
        headers=headers,
        json={
            "email": "blocked@test.com",
            "full_name": "Blocked",
            "role": "viewer",
        },
    )
    assert res.status_code == 403

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    admin = await _seed_user(
        db_session,
        email="sole-admin@test.com",
        role="admin",
        full_name="Sole Admin",
    )
    headers = {"Authorization": f"Bearer {_token_for(admin, role='admin')}"}

    res = await client.patch(
        f"/api/tenants/current/members/{admin.id}",
        headers=headers,
        json={"role": "viewer"},
    )
    assert res.status_code == 400

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invite_accept_creates_auth_and_membership(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    admin = await _seed_user(
        db_session,
        email="invite-admin@test.com",
        role="admin",
        full_name="Invite Admin",
    )
    headers = {"Authorization": f"Bearer {_token_for(admin, role='admin')}"}

    invited = await client.post(
        "/api/tenants/current/members/invite",
        headers=headers,
        json={
            "email": "accept-me@test.com",
            "full_name": "Accept Me",
            "role": "auditor",
        },
    )
    assert invited.status_code == 200
    accept_url = invited.json()["data"]["accept_url"]
    token = accept_url.split("token=")[1]

    preview = await client.get(f"/api/auth/invite/preview?token={token}")
    assert preview.status_code == 200
    assert preview.json()["data"]["email"] == "accept-me@test.com"
    assert preview.json()["data"]["role"] == "auditor"

    accepted = await client.post(
        "/api/auth/invite/accept",
        json={
            "token": token,
            "password": "newpassword1",
            "full_name": "Accept Me",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["email"] == "accept-me@test.com"

    listed = await client.get("/api/tenants/current/members", headers=headers)
    members = listed.json()["data"]["members"]
    assert any(m["email"] == "accept-me@test.com" and m["role"] == "auditor" for m in members)

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_permissions_endpoint_returns_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    user = await _seed_user(
        db_session,
        email="perms-user@test.com",
        role="bookkeeper",
        full_name="Bookkeeper",
    )
    headers = {"Authorization": f"Bearer {_token_for(user, role='bookkeeper')}"}

    res = await client.get("/api/auth/me/permissions", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["role"] == "bookkeeper"
    assert data["matrix_role"] == "Bookkeeper"
    assert data["permissions"]["View"] is True
    assert data["permissions"]["Approve"] is False

    get_settings.cache_clear()
