"""Platform tenant service tests."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.user_tenant_mapping import UserTenantMapping
from app.schemas.platform import CreatePlatformTenantRequest, DeletePlatformTenantRequest
from app.services.auth_service import hash_password
from app.services.platform_service import (
    create_client_tenant,
    delete_client_tenant,
    list_client_tenants,
    provision_client_tenant_access,
)
from app.tenant_roles import TenantRole


@pytest.mark.asyncio
async def test_list_client_tenants_excludes_platform_tenant(db_session: AsyncSession) -> None:
    import uuid

    db_session.add(
        Tenant(id=uuid.uuid4(), name="Acme Client", slug="acme-client", is_platform=False)
    )
    db_session.add(
        Tenant(id=uuid.uuid4(), name="LedgerLink Platform", slug="platform", is_platform=True)
    )
    await db_session.flush()

    tenants = await list_client_tenants(db_session)
    slugs = {t.slug for t in tenants}
    assert "platform" not in slugs
    assert "acme-client" in slugs


@pytest.mark.asyncio
async def test_create_client_tenant_seeds_modules(db_session: AsyncSession) -> None:
    tenant = await create_client_tenant(
        db_session,
        CreatePlatformTenantRequest(name="New Client", slug="new-client"),
    )
    assert tenant.slug == "new-client"
    assert len(tenant.modules) == 5
    assert all(m.is_active for m in tenant.modules)


@pytest.mark.asyncio
async def test_create_client_tenant_provisions_operator_admin(db_session: AsyncSession) -> None:
    platform_id = uuid.uuid4()
    db_session.add(
        Tenant(
            id=platform_id,
            name="LedgerLink Platform",
            slug="platform",
            is_platform=True,
        )
    )
    account = AuthAccount(
        email="ops@ledgerlink.test",
        password_hash=hash_password("password123"),
    )
    db_session.add(account)
    await db_session.flush()

    operator = User(
        tenant_id=platform_id,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="Platform Ops",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    db_session.add(operator)
    await db_session.flush()

    tenant = await create_client_tenant(
        db_session,
        CreatePlatformTenantRequest(name="Acme", slug="acme"),
        operator_user_id=operator.id,
    )
    assert tenant.user_count == 1

    client_user = (
        await db_session.execute(select(User).where(User.tenant_id == tenant.id))
    ).scalar_one()
    assert client_user.email == account.email
    assert client_user.role == UserRole.ADMIN

    mapping = (
        await db_session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == client_user.id,
                UserTenantMapping.tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    assert mapping.role == TenantRole.ADMIN.value


@pytest.mark.asyncio
async def test_provision_client_tenant_access_is_idempotent(db_session: AsyncSession) -> None:
    platform_id = uuid.uuid4()
    client_id = uuid.uuid4()
    db_session.add_all(
        [
            Tenant(id=platform_id, name="Platform", slug="platform", is_platform=True),
            Tenant(id=client_id, name="Client", slug="client", is_platform=False),
        ]
    )
    account = AuthAccount(
        email="ops@ledgerlink.test",
        password_hash=hash_password("password123"),
    )
    db_session.add(account)
    await db_session.flush()

    operator = User(
        tenant_id=platform_id,
        auth_account_id=account.id,
        email=account.email,
        password_hash=account.password_hash,
        full_name="Platform Ops",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    db_session.add(operator)
    await db_session.flush()

    first = await provision_client_tenant_access(
        db_session, tenant_id=client_id, operator_user_id=operator.id
    )
    second = await provision_client_tenant_access(
        db_session, tenant_id=client_id, operator_user_id=operator.id
    )
    assert first.id == second.id

    user_count = (
        await db_session.execute(
            select(func.count()).select_from(User).where(User.tenant_id == client_id)
        )
    ).scalar_one()
    assert int(user_count) == 1


@pytest.mark.asyncio
async def test_delete_client_tenant_removes_tenant_and_users(db_session: AsyncSession) -> None:
    client_id = uuid.uuid4()
    db_session.add(Tenant(id=client_id, name="Gone Co", slug="gone-co", is_platform=False))
    db_session.add(
        User(
            tenant_id=client_id,
            email="admin@gone.test",
            password_hash=hash_password("password123"),
            full_name="Gone Admin",
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    await db_session.flush()

    deleted = await delete_client_tenant(
        db_session,
        tenant_id=client_id,
        body=DeletePlatformTenantRequest(confirm_slug="gone-co"),
    )
    assert deleted is True
    assert await db_session.get(Tenant, client_id) is None
    users_left = (
        await db_session.execute(select(func.count()).select_from(User).where(User.tenant_id == client_id))
    ).scalar_one()
    assert int(users_left) == 0


@pytest.mark.asyncio
async def test_delete_client_tenant_rejects_wrong_slug(db_session: AsyncSession) -> None:
    client_id = uuid.uuid4()
    db_session.add(Tenant(id=client_id, name="Keep Co", slug="keep-co", is_platform=False))
    await db_session.flush()

    with pytest.raises(ValueError, match="Confirmation slug"):
        await delete_client_tenant(
            db_session,
            tenant_id=client_id,
            body=DeletePlatformTenantRequest(confirm_slug="wrong"),
        )


@pytest.mark.asyncio
async def test_delete_client_tenant_blocks_platform_tenant(db_session: AsyncSession) -> None:
    platform_id = uuid.uuid4()
    db_session.add(
        Tenant(id=platform_id, name="Platform", slug="platform", is_platform=True)
    )
    await db_session.flush()

    with pytest.raises(ValueError, match="Platform tenant"):
        await delete_client_tenant(
            db_session,
            tenant_id=platform_id,
            body=DeletePlatformTenantRequest(confirm_slug="platform"),
        )
