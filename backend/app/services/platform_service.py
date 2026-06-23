"""Platform super-admin tenant management."""

from sqlalchemy import delete, func, select
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.mailbox_connection_request import MailboxConnectionRequest
from app.models.mailbox_sync_job import MailboxSyncJob
from app.models.meta_webhook_dedupe import MetaWebhookDedupe
from app.models.payment import Payment
from app.models.purchase_order import PurchaseOrder
from app.models.reconciliation import DailyReconciliation
from app.models.tenant import Tenant
from app.models.tenant_module import TenantModule
from app.models.user import User, UserRole
from app.models.user_tenant_mapping import UserTenantMapping
from app.models.connected_mailbox import ConnectedMailbox
from app.models.connected_whatsapp import ConnectedWhatsapp
from app.models.employee_master import EmployeeMasterRecord
from app.models.goods_receipt import GoodsReceipt
from app.models.pending_vendor import PendingVendor
from app.models.vendor import VendorRegistry
from app.models.vendor_master import VendorMasterRecord
from app.services.approval_policy_io import remove_policy_for_tenant
from app.services.billing_io import load_billing_for_tenant, remove_billing_for_tenant
from app.services.membership_service import ensure_membership
from app.services.rule_book_config_io import _legacy_file_paths_for_tenant
from app.services.rule_book_config_repository import ensure_default_config
from app.tenant_settings import default_institution_settings
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    DeletePlatformTenantRequest,
    PlatformTenantDetail,
    PlatformTenantModule,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.tenant_roles import TenantRole

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


async def provision_client_tenant_access(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operator_user_id: int,
) -> User:
    """Give a platform operator an admin user + membership on a client tenant."""
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or tenant.is_platform:
        raise ValueError("Client tenant not found")

    operator = await session.get(User, operator_user_id)
    if not operator or not operator.is_active:
        raise ValueError("Operator user not found")

    client_user = (
        await session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.auth_account_id == operator.auth_account_id,
            )
        )
    ).scalar_one_or_none()
    if client_user is None:
        client_user = User(
            tenant_id=tenant_id,
            auth_account_id=operator.auth_account_id,
            email=operator.email,
            password_hash=operator.password_hash,
            full_name=operator.full_name,
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(client_user)
        await session.flush()
    else:
        client_user.is_active = True
        client_user.role = UserRole.ADMIN

    mapping = (
        await session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == client_user.id,
                UserTenantMapping.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if mapping:
        mapping.role = TenantRole.ADMIN.value
        mapping.status = "active"
        mapping.is_active = True
    else:
        await ensure_membership(
            session,
            user_id=client_user.id,
            tenant_id=tenant_id,
            role=TenantRole.ADMIN.value,
        )

    await ensure_default_config(session, tenant_id)
    await session.flush()
    return client_user


async def create_client_tenant(
    session: AsyncSession,
    body: CreatePlatformTenantRequest,
    *,
    operator_user_id: int | None = None,
) -> PlatformTenantDetail:
    tenant = Tenant(
        name=body.name.strip(),
        slug=body.slug.strip().lower(),
        is_active=True,
        is_platform=False,
        lifecycle_status="active",
        settings_json=default_institution_settings(),
    )
    session.add(tenant)
    await session.flush()
    await _seed_modules(session, tenant.id)
    await ensure_default_config(session, tenant.id)
    if operator_user_id is not None:
        await provision_client_tenant_access(
            session,
            tenant_id=tenant.id,
            operator_user_id=operator_user_id,
        )
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


def _remove_tenant_files(tenant_id: uuid.UUID) -> None:
    for path in _legacy_file_paths_for_tenant(tenant_id):
        if path.is_file():
            path.unlink(missing_ok=True)


async def delete_client_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    body: DeletePlatformTenantRequest,
) -> bool:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        return False
    if tenant.is_platform:
        raise ValueError("Platform tenant cannot be deleted")
    if tenant.slug != body.confirm_slug.strip().lower():
        raise ValueError("Confirmation slug does not match")

    tid = tenant_id
    await session.execute(delete(LineItem).where(LineItem.tenant_id == tid))
    await session.execute(delete(JournalEntry).where(JournalEntry.tenant_id == tid))
    await session.execute(delete(GoodsReceipt).where(GoodsReceipt.tenant_id == tid))
    await session.execute(delete(Payment).where(Payment.tenant_id == tid))
    await session.execute(delete(Invoice).where(Invoice.tenant_id == tid))
    await session.execute(delete(PurchaseOrder).where(PurchaseOrder.tenant_id == tid))
    await session.execute(delete(MetaWebhookDedupe).where(MetaWebhookDedupe.tenant_id == tid))
    await session.execute(delete(MailboxSyncJob).where(MailboxSyncJob.tenant_id == tid))
    await session.execute(
        delete(MailboxConnectionRequest).where(MailboxConnectionRequest.tenant_id == tid)
    )
    await session.execute(delete(ConnectedMailbox).where(ConnectedMailbox.tenant_id == tid))
    await session.execute(delete(ConnectedWhatsapp).where(ConnectedWhatsapp.tenant_id == tid))
    await session.execute(delete(PendingVendor).where(PendingVendor.tenant_id == tid))
    await session.execute(delete(VendorMasterRecord).where(VendorMasterRecord.tenant_id == tid))
    await session.execute(
        delete(EmployeeMasterRecord).where(EmployeeMasterRecord.tenant_id == tid)
    )
    await session.execute(delete(VendorRegistry).where(VendorRegistry.tenant_id == tid))
    await session.execute(
        delete(DailyReconciliation).where(DailyReconciliation.tenant_id == tid)
    )
    await session.execute(delete(User).where(User.tenant_id == tid))
    await session.delete(tenant)
    await session.flush()

    remove_billing_for_tenant(tid)
    remove_policy_for_tenant(tid)
    _remove_tenant_files(tid)
    return True
