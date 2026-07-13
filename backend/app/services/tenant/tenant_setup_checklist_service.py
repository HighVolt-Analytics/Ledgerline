"""Evaluate tenant admin setup checklist from existing subsystem state."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.tenant_member_invite import TenantMemberInvite
from app.models.user import User
from app.models.user_tenant_mapping import UserTenantMapping
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.schemas.setup_checklist import SetupChecklistItem, SetupChecklistStateResponse
from app.services.rule_book.account_mapper import category_resolved_in_coa, coa_functional_for_journaling
from app.services.rule_book.rule_book_config_io import load_posting_config_payload
from app.tenant_settings import (
    tenant_industry,
    tenant_setup_checklist_complete,
)

_CHECKLIST_DEFS: list[dict] = [
    {
        "id": "profile_name",
        "label": "Complete organisation profile",
        "group": "Getting started",
        "route": "/settings?tab=profile",
    },
    {
        "id": "profile_industry",
        "label": "Choose your industry",
        "group": "Getting started",
        "route": "/settings?tab=profile",
    },
    {
        "id": "profile_country",
        "label": "Confirm business country",
        "group": "Getting started",
        "route": "/settings?tab=profile",
    },
    {
        "id": "team_invite",
        "label": "Invite a team member",
        "group": "Getting started",
        "route": "/settings?tab=team",
        "optional": True,
    },
    {
        "id": "connect_mailbox",
        "label": "Connect your mailbox",
        "group": "Getting started",
        "route": "/integrations",
    },
    {
        "id": "chart_of_accounts",
        "label": "Configure chart of accounts",
        "group": "Getting started",
        "route": "/settings?tab=coa",
    },
    {
        "id": "first_document",
        "label": "Upload your first document",
        "group": "Getting started",
        "route": "/upload",
    },
    {
        "id": "review_rules",
        "label": "Review your rules",
        "group": "Getting started",
        "route": "/rules",
        "optional": True,
    },
    {
        "id": "check_ledgerlink",
        "label": "Connect accounting (LedgerLink)",
        "group": "Getting started",
        "route": "/ledger-link",
        "optional": True,
    },
]


async def _item_done(
    session: AsyncSession,
    *,
    tenant: Tenant,
    item_id: str,
) -> bool:
    tenant_id = tenant.id
    if item_id == "profile_name":
        return bool(tenant.name and tenant.name.strip())
    if item_id == "profile_industry":
        return tenant_industry(tenant) is not None
    if item_id == "profile_country":
        from app.tenant_settings import tenant_country

        return bool(tenant_country(tenant))
    if item_id == "team_invite":
        member_count = (
            await session.execute(
                select(func.count())
                .select_from(UserTenantMapping)
                .where(
                    UserTenantMapping.tenant_id == tenant_id,
                    UserTenantMapping.is_active.is_(True),
                    UserTenantMapping.status == "active",
                )
            )
        ).scalar_one()
        pending_invites = (
            await session.execute(
                select(func.count())
                .select_from(TenantMemberInvite)
                .where(
                    TenantMemberInvite.tenant_id == tenant_id,
                    TenantMemberInvite.accepted_at.is_(None),
                )
            )
        ).scalar_one()
        return int(member_count or 0) > 1 or int(pending_invites or 0) > 0
    if item_id == "connect_mailbox":
        count = (
            await session.execute(
                select(func.count())
                .select_from(ConnectedMailbox)
                .where(ConnectedMailbox.tenant_id == tenant_id)
            )
        ).scalar_one()
        return int(count or 0) > 0
    if item_id == "chart_of_accounts":
        config = await load_posting_config_payload(session, tenant_id)
        return coa_functional_for_journaling(config)
    if item_id == "first_document":
        count = (
            await session.execute(
                select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
            )
        ).scalar_one()
        return int(count or 0) > 0
    if item_id in ("review_rules", "check_ledgerlink"):
        # Optional navigation-only tasks; completion can be tracked later if needed.
        return False
    return False


async def build_setup_checklist_state(
    session: AsyncSession,
    *,
    tenant: Tenant,
    user_role: str,
    is_support_session: bool,
) -> SetupChecklistStateResponse:
    if is_support_session:
        return SetupChecklistStateResponse(complete=False, show=False, progress=0, items=[])

    items: list[SetupChecklistItem] = []
    done_count = 0
    for spec in _CHECKLIST_DEFS:
        done = await _item_done(session, tenant=tenant, item_id=spec["id"])
        if done:
            done_count += 1
        items.append(
            SetupChecklistItem(
                id=spec["id"],
                label=spec["label"],
                group=spec["group"],
                done=done,
                route=spec["route"],
                optional=bool(spec.get("optional")),
            )
        )

    required = [i for i in items if not i.optional]
    required_done = sum(1 for i in required if i.done)
    progress = int((required_done / len(required)) * 100) if required else 100
    if tenant_setup_checklist_complete(tenant):
        progress = 100
    all_required_done = all(i.done for i in required)
    complete = all_required_done or tenant_setup_checklist_complete(tenant)

    # The checklist is the "get started" surface; show it until completion.
    show = not complete

    return SetupChecklistStateResponse(
        complete=complete,
        show=show,
        progress=progress,
        items=items,
    )
