"""OTP login flow tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_account import AuthAccount
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from app.services.membership_service import ensure_membership


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
        tenant_id=1,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="OTP User",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(db_session, user_id=user.id, tenant_id=1)
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
    assert body["user"]["tenant_id"] == 1

    get_settings.cache_clear()
