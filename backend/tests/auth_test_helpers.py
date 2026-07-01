"""Seed users and tokens for API tests (register endpoint removed; OTP or JWT)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID


async def seed_admin_user(
    db_session: AsyncSession,
    *,
    email: str = "admin@test.example.com",
    password: str = "securepass1",
    full_name: str = "Test Admin",
    tenant_id: uuid.UUID = TESTING_TENANT_UUID,
    tenant_slug: str = "hv-org",
    role: UserRole = UserRole.ADMIN,
) -> tuple[User, str]:
    account = AuthAccount(email=email, password_hash=hash_password(password))
    db_session.add(account)
    await db_session.flush()

    user = User(
        tenant_id=tenant_id,
        auth_account_id=account.id,
        email=email,
        password_hash=account.password_hash,
        full_name=full_name,
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(
        db_session, user_id=user.id, tenant_id=tenant_id, role=role.value
    )

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        email=email,
        role=role.value,
    )
    return user, token


async def login_via_otp(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str = "otp-admin@test.example.com",
    password: str = "securepass1",
    tenant_id: uuid.UUID = TESTING_TENANT_UUID,
    tenant_slug: str = "hv-org",
) -> str:
    """Full login challenge + verify-otp (dev OTP 123456)."""
    await seed_admin_user(
        db_session,
        email=email,
        password=password,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
    )
    await db_session.commit()

    login = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    challenge = login.json()["data"]["challenge_token"]

    verify = await client.post(
        "/api/auth/verify-otp",
        json={"otp": "123456"},
        headers={"Authorization": f"Bearer {challenge}"},
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["data"]["access_token"]
