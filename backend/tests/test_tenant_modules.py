"""Tenant module entitlement tests."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
from app.models.user import User, UserRole
from app.schemas.platform import PlatformTenantModule, UpdatePlatformTenantRequest
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.services.tenant.platform_service import update_client_tenant
from app.services.tenant.tenant_module_service import enabled_modules_map, validate_module_keys
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_modules import TOGGLEABLE_MODULE_KEYS


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
async def test_enabled_modules_map_defaults_missing_row_to_true(
    db_session: AsyncSession,
) -> None:
    modules = await enabled_modules_map(db_session, TESTING_TENANT_UUID)
    assert modules["vault"] is True
    assert modules["purchase"] is True
    assert set(modules) == set(TOGGLEABLE_MODULE_KEYS)


@pytest.mark.asyncio
async def test_enabled_modules_map_respects_disabled_row(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="vault",
            is_active=False,
        )
    )
    await db_session.flush()

    modules = await enabled_modules_map(db_session, TESTING_TENANT_UUID)
    assert modules["vault"] is False
    assert modules["purchase"] is True


def test_validate_module_keys_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown module keys"):
        validate_module_keys(["vault", "not_a_real_module"])


@pytest.mark.asyncio
async def test_update_client_tenant_rejects_unknown_module_key(
    db_session: AsyncSession,
) -> None:
    client_id = uuid.uuid4()
    db_session.add(
        Tenant(id=client_id, name="Module Client", slug="module-client", is_platform=False)
    )
    await db_session.flush()

    with pytest.raises(ValueError, match="Unknown module keys"):
        await update_client_tenant(
            db_session,
            tenant_id=client_id,
            body=UpdatePlatformTenantRequest(
                modules=[PlatformTenantModule(module_key="fake_module", is_active=True)]
            ),
        )


@pytest.mark.asyncio
async def test_vault_api_returns_403_when_module_disabled(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="vault",
            is_active=False,
        )
    )
    await db_session.flush()

    user = await _seed_user(
        db_session,
        email="vault-blocked@test.com",
        role="admin",
        full_name="Vault Blocked",
    )
    headers = {"Authorization": f"Bearer {_token_for(user, role='admin')}"}

    res = await client.get("/api/vault/tree", headers=headers)
    assert res.status_code == 403
    assert "Module disabled: vault" in res.json()["detail"]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_permissions_endpoint_includes_enabled_modules(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    db_session.add(
        TenantModule(
            tenant_id=TESTING_TENANT_UUID,
            module_key="payments",
            is_active=False,
        )
    )
    await db_session.flush()

    user = await _seed_user(
        db_session,
        email="modules-perms@test.com",
        role="admin",
        full_name="Modules Perms",
    )
    headers = {"Authorization": f"Bearer {_token_for(user, role='admin')}"}

    res = await client.get("/api/auth/me/permissions", headers=headers)
    assert res.status_code == 200
    modules = res.json()["data"]["enabled_modules"]
    assert modules["payments"] is False
    assert modules["vault"] is True
    assert set(modules) == set(TOGGLEABLE_MODULE_KEYS)

    get_settings.cache_clear()
