"""OTP login flow tests."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from app.services.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_login_verify_otp_issues_tokens(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    account = AuthAccount(
        email="otp-user@example.com",
        password_hash=hash_password("password123"),
    )
    db_session.add(account)
    await db_session.flush()

    user = User(
        tenant_id=TESTING_TENANT_UUID,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="OTP User",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=TESTING_TENANT_UUID)
    await db_session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": account.email, "password": "password123"},
    )
    assert login.status_code == 200
    challenge = login.json()["data"]["challenge_token"]

    verify = await client.post(
        "/api/auth/verify-otp",
        json={"otp": "123456"},
        headers={"Authorization": f"Bearer {challenge}"},
    )
    assert verify.status_code == 200
    body = verify.json()["data"]
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["tenant_id"] == str(TESTING_TENANT_UUID)

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_verify_otp_multi_tenant_returns_picker(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    other_tid = uuid.uuid4()
    db_session.add(Tenant(id=other_tid, name="Second Org", slug="second-org", is_active=True))

    account = AuthAccount(
        email="multi-tenant@example.com",
        password_hash=hash_password("password123"),
    )
    db_session.add(account)
    await db_session.flush()

    user_a = User(
        tenant_id=TESTING_TENANT_UUID,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="Multi Tenant",
        role=UserRole.ADMIN,
    )
    user_b = User(
        tenant_id=other_tid,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="Multi Tenant",
        role=UserRole.MEMBER,
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()
    await ensure_membership(db_session, user_id=user_a.id, tenant_id=TESTING_TENANT_UUID)
    await ensure_membership(db_session, user_id=user_b.id, tenant_id=other_tid)
    await db_session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": account.email, "password": "password123"},
    )
    assert login.status_code == 200
    challenge = login.json()["data"]["challenge_token"]

    verify = await client.post(
        "/api/auth/verify-otp",
        json={"otp": "123456"},
        headers={"Authorization": f"Bearer {challenge}"},
    )
    assert verify.status_code == 200
    body = verify.json()["data"]
    assert body["multi_tenant"] is True
    assert body["tenant_select_token"]
    assert len(body["accounts"]) == 2
    tenant_ids = {row["tenant_id"] for row in body["accounts"]}
    assert str(TESTING_TENANT_UUID) in tenant_ids
    assert str(other_tid) in tenant_ids

    get_settings.cache_clear()
