"""Platform super-admin tenant management."""

from datetime import datetime, timezone

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
from app.models.tenant_member_invite import TenantMemberInvite
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
from app.services.approval.approval_policy_io import remove_policy_for_tenant
from app.services.shared.billing_io import remove_billing_for_tenant
from app.services.credit_service import (
    ensure_tenant_billing,
    get_credits_per_page,
    refresh_tenant_billing,
    tenant_azure_cost_total_usd,
    tenant_credits_consumed,
)
from app.tenant_settings import tenant_country
from app.services.auth.membership_service import ensure_membership
from app.services.rule_book.rule_book_config_io import _legacy_file_paths_for_tenant
from app.services.rule_book.rule_book_config_repository import ensure_default_config
from app.services.tenant.tenant_members_service import (
    InviteCreated,
    create_invite,
    list_tenant_members,
)
from app.tenant_rls import apply_rls_session_context
from app.tenant_settings import build_tenant_settings
from app.schemas.platform import (
    CreatePlatformTenantRequest,
    DeletePlatformTenantRequest,
    PlatformTenantDetail,
    PlatformTenantModule,
    PlatformTenantSummary,
    UpdatePlatformTenantRequest,
)
from app.services.tenant.tenant_module_service import ensure_module_rows, validate_module_keys
from app.tenant_modules import CATALOG_BY_KEY, TOGGLEABLE_MODULE_KEYS
from app.tenant_roles import TenantRole


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _batch_tenant_counts(
    session: AsyncSession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    if not tenant_ids:
        return {}

    user_rows = (
        await session.execute(
            select(UserTenantMapping.tenant_id, func.count(func.distinct(User.id)))
            .select_from(UserTenantMapping)
            .join(User, UserTenantMapping.user_id == User.id)
            .where(
                UserTenantMapping.tenant_id.in_(tenant_ids),
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
                User.is_active.is_(True),
                User.is_platform_shadow.is_(False),
            )
            .group_by(UserTenantMapping.tenant_id)
        )
    ).all()
    user_by_tenant = {row[0]: int(row[1]) for row in user_rows}

    invoice_rows = (
        await session.execute(
            select(Invoice.tenant_id, func.count())
            .where(Invoice.tenant_id.in_(tenant_ids))
            .group_by(Invoice.tenant_id)
        )
    ).all()
    invoice_by_tenant = {row[0]: int(row[1]) for row in invoice_rows}

    now = _utc_now()
    invite_rows = (
        await session.execute(
            select(TenantMemberInvite.tenant_id, func.count())
            .where(
                TenantMemberInvite.tenant_id.in_(tenant_ids),
                TenantMemberInvite.accepted_at.is_(None),
                TenantMemberInvite.expires_at > now,
            )
            .group_by(TenantMemberInvite.tenant_id)
        )
    ).all()
    invite_by_tenant = {row[0]: int(row[1]) for row in invite_rows}

    return {
        tenant_id: (
            user_by_tenant.get(tenant_id, 0),
            invoice_by_tenant.get(tenant_id, 0),
            invite_by_tenant.get(tenant_id, 0),
        )
        for tenant_id in tenant_ids
    }


async def _tenant_counts(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, int, int]:
    user_count = (
        await session.execute(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(
                UserTenantMapping,
                (UserTenantMapping.user_id == User.id)
                & (UserTenantMapping.tenant_id == tenant_id),
            )
            .where(
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
                User.is_active.is_(True),
                User.is_platform_shadow.is_(False),
            )
        )
    ).scalar_one()
    invoice_count = (
        await session.execute(
            select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
        )
    ).scalar_one()
    now = _utc_now()
    pending_invite_count = (
        await session.execute(
            select(func.count())
            .select_from(TenantMemberInvite)
            .where(
                TenantMemberInvite.tenant_id == tenant_id,
                TenantMemberInvite.accepted_at.is_(None),
                TenantMemberInvite.expires_at > now,
            )
        )
    ).scalar_one()
    return int(user_count), int(invoice_count), int(pending_invite_count)


async def _modules_for_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> list[PlatformTenantModule]:
    rows = (
        await session.execute(
            select(TenantModule).where(TenantModule.tenant_id == tenant_id).order_by(TenantModule.module_key)
        )
    ).scalars().all()
    return [
        PlatformTenantModule(module_key=row.module_key, is_active=row.is_active) for row in rows
    ]


async def _to_summary(
    session: AsyncSession,
    tenant: Tenant,
    *,
    user_count: int,
    invoice_count: int,
    pending_invite_count: int,
) -> PlatformTenantSummary:
    billing = await refresh_tenant_billing(session, tenant.id)
    consumed = await tenant_credits_consumed(session, tenant.id)
    azure_total = await tenant_azure_cost_total_usd(session, tenant.id)
    cpp = await get_credits_per_page(session, billing)
    return PlatformTenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
        lifecycle_status=tenant.lifecycle_status,
        created_at=tenant.created_at,
        user_count=user_count,
        pending_invite_count=pending_invite_count,
        invoice_count=invoice_count,
        credit_balance=billing.credit_balance,
        credits_consumed=consumed,
        azure_cost_usd_total=float(azure_total),
        plan=billing.plan,
        country=tenant_country(tenant),
        credits_per_page=cpp,
    )


async def list_client_tenants(session: AsyncSession) -> list[PlatformTenantSummary]:
    tenants = (
        await session.execute(
            select(Tenant)
            .where(Tenant.is_platform.is_(False))
            .order_by(Tenant.name)
        )
    ).scalars().all()

    counts = await _batch_tenant_counts(session, [tenant.id for tenant in tenants])
    summaries: list[PlatformTenantSummary] = []
    for tenant in tenants:
        c = counts.get(tenant.id, (0, 0, 0))
        summaries.append(
            await _to_summary(
                session,
                tenant,
                user_count=c[0],
                invoice_count=c[1],
                pending_invite_count=c[2],
            )
        )
    return summaries


async def get_client_tenant(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> PlatformTenantDetail | None:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or tenant.is_platform:
        return None

    await ensure_module_rows(session, tenant_id)

    user_count, invoice_count, pending_invite_count = await _tenant_counts(session, tenant.id)
    summary = await _to_summary(
        session,
        tenant,
        user_count=user_count,
        invoice_count=invoice_count,
        pending_invite_count=pending_invite_count,
    )
    modules = await _modules_for_tenant(session, tenant.id)
    billing = await refresh_tenant_billing(session, tenant.id)
    return PlatformTenantDetail(
        **summary.model_dump(),
        settings_json=tenant.settings_json,
        modules=modules,
        credits_per_page_override=billing.credits_per_page_override,
        enterprise_monthly_credits=billing.enterprise_monthly_credits,
        billing_anchor_date=billing.billing_anchor_date.isoformat(),
    )


async def list_client_tenant_members(
    session: AsyncSession, *, tenant_id: uuid.UUID
):
    """List users and pending invites for a client tenant (RLS-scoped)."""
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or tenant.is_platform:
        return None

    await apply_rls_session_context(session, tenant_id)
    return await list_tenant_members(session, tenant_id=tenant_id)


async def _seed_modules(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    for key in TOGGLEABLE_MODULE_KEYS:
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
        mod = CATALOG_BY_KEY[key]
        session.add(
            TenantModule(
                tenant_id=tenant_id,
                module_key=key,
                is_active=mod.default_active,
            )
        )
    await session.flush()


async def provision_client_tenant_access(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operator_user_id: int,
) -> User:
    """Legacy shadow-user helper — no longer exposed via API (org data isolation)."""
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
            is_platform_shadow=True,
        )
        session.add(client_user)
        await session.flush()
    else:
        client_user.is_active = True
        if client_user.is_platform_shadow:
            client_user.role = UserRole.ADMIN
        # Reuse the tenant's real member row for support sessions — never mark
        # an existing non-shadow user as a platform shadow (breaks user counts).

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


async def invite_tenant_admin(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    full_name: str,
    invited_by_user_id: int | None,
) -> InviteCreated:
    """Create an admin invite for a client tenant (platform or tenant context)."""
    return await create_invite(
        session,
        tenant_id=tenant_id,
        email=email,
        full_name=full_name,
        role=TenantRole.ADMIN.value,
        invited_by_user_id=invited_by_user_id,
    )


async def create_client_tenant(
    session: AsyncSession,
    body: CreatePlatformTenantRequest,
    *,
    invited_by_user_id: int | None = None,
) -> tuple[PlatformTenantDetail, InviteCreated]:
    settings_json = build_tenant_settings(
        country=body.country,
        industry=body.industry,
        onboarding_completed=False,
    )
    tenant = Tenant(
        name=body.name.strip(),
        slug=body.slug.strip().lower(),
        is_active=True,
        is_platform=False,
        lifecycle_status="active",
        settings_json=settings_json,
    )
    session.add(tenant)
    await session.flush()
    await _seed_modules(session, tenant.id)
    await ensure_default_config(session, tenant.id)
    await ensure_tenant_billing(session, tenant.id, plan="free")

    invite = await invite_tenant_admin(
        session,
        tenant_id=tenant.id,
        email=str(body.first_admin_email),
        full_name=body.first_admin_name,
        invited_by_user_id=invited_by_user_id,
    )

    detail = await get_client_tenant(session, tenant_id=tenant.id)
    assert detail is not None
    return detail, invite


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
        validate_module_keys([mod.module_key for mod in body.modules])
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


async def repair_misclassified_platform_shadow_users(session: AsyncSession) -> int:
    """Unset shadow flag on real tenant owners incorrectly marked by migration 036."""
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(
                """
                UPDATE users AS u
                SET is_platform_shadow = FALSE
                FROM (
                    SELECT tenant_id, MIN(id) AS first_user_id
                    FROM users
                    WHERE tenant_id IN (
                        SELECT id FROM tenants WHERE is_platform = FALSE
                    )
                    GROUP BY tenant_id
                ) AS first_per_tenant
                WHERE u.id = first_per_tenant.first_user_id
                  AND u.is_platform_shadow = TRUE
                RETURNING u.id
                """
            )
        )
    ).fetchall()
    await session.flush()
    return len(rows)
