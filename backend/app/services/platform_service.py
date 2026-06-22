"""Platform super-admin tenant management."""

from sqlalchemy import func, select
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
from app.models.user import User
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    PlatformTenantDetail,
    PlatformTenantModule,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.services.billing_io import load_billing_for_tenant

_DEFAULT_MODULES = ("purchase", "expenses", "team_expenses", "vault", "rule_book")


async def _tenant_counts(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, int]:
    user_count = (
        await session.execute(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        )
    ).scalar_one()
    invoice_count = (
        await session.execute(
            select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
        )
    ).scalar_one()
    return int(user_count), int(invoice_count)


async def _modules_for_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> list[PlatformTenantModule]:
    rows = (
        await session.execute(
            select(TenantModule).where(TenantModule.tenant_id == tenant_id).order_by(TenantModule.module_key)
        )
    ).scalars().all()
    return [
        PlatformTenantModule(module_key=row.module_key, is_active=row.is_active) for row in rows
    ]


def _to_summary(
    tenant: Tenant,
    *,
    user_count: int,
    invoice_count: int,
) -> PlatformTenantSummary:
    billing = load_billing_for_tenant(tenant.id)
    return PlatformTenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
        lifecycle_status=tenant.lifecycle_status,
        created_at=tenant.created_at,
        user_count=user_count,
        invoice_count=invoice_count,
        credit_balance=billing.balance,
    )


async def list_client_tenants(session: AsyncSession) -> list[PlatformTenantSummary]:
    tenants = (
        await session.execute(
            select(Tenant)
            .where(Tenant.is_platform.is_(False))
            .order_by(Tenant.name)
        )
    ).scalars().all()

    results: list[PlatformTenantSummary] = []
    for tenant in tenants:
        user_count, invoice_count = await _tenant_counts(session, tenant.id)
        results.append(
            _to_summary(tenant, user_count=user_count, invoice_count=invoice_count)
        )
    return results


async def get_client_tenant(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> PlatformTenantDetail | None:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or tenant.is_platform:
        return None

    user_count, invoice_count = await _tenant_counts(session, tenant.id)
    summary = _to_summary(tenant, user_count=user_count, invoice_count=invoice_count)
    modules = await _modules_for_tenant(session, tenant.id)
    return PlatformTenantDetail(
        **summary.model_dump(),
        settings_json=tenant.settings_json,
        modules=modules,
    )


async def _seed_modules(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    for key in _DEFAULT_MODULES:
        existing = (
            await session.execute(
                select(TenantModule).where(
                    TenantModule.tenant_id == tenant_id,
                    TenantModule.module_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(TenantModule(tenant_id=tenant_id, module_key=key, is_active=True))
    await session.flush()


async def create_client_tenant(
    session: AsyncSession, body: CreatePlatformTenantRequest
) -> PlatformTenantDetail:
    tenant = Tenant(
        name=body.name.strip(),
        slug=body.slug.strip().lower(),
        is_active=True,
        is_platform=False,
        lifecycle_status="active",
    )
    session.add(tenant)
    await session.flush()
    await _seed_modules(session, tenant.id)
    detail = await get_client_tenant(session, tenant_id=tenant.id)
    assert detail is not None
    return detail


async def update_client_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    body: UpdatePlatformTenantRequest,
) -> PlatformTenantDetail | None:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or tenant.is_platform:
        return None

    if body.name is not None:
        tenant.name = body.name.strip()
    if body.is_active is not None:
        tenant.is_active = body.is_active
    if body.lifecycle_status is not None:
        tenant.lifecycle_status = body.lifecycle_status
    if body.settings_json is not None:
        tenant.settings_json = body.settings_json

    if body.modules is not None:
        for mod in body.modules:
            row = (
                await session.execute(
                    select(TenantModule).where(
                        TenantModule.tenant_id == tenant_id,
                        TenantModule.module_key == mod.module_key,
                    )
                )
            ).scalar_one_or_none()
            if row:
                row.is_active = mod.is_active
            else:
                session.add(
                    TenantModule(
                        tenant_id=tenant_id,
                        module_key=mod.module_key,
                        is_active=mod.is_active,
                    )
                )

    await session.flush()
    return await get_client_tenant(session, tenant_id=tenant_id)
