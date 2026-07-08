"""Evaluate tenant admin setup checklist from existing subsystem state."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.tenant_member_invite import TenantMemberInvite
from app.models.user import User
from app.models.user_tenant_mapping import UserTenantMapping
from app.schemas.setup_checklist import SetupChecklistItem, SetupChecklistStateResponse
from app.services.master_data.chart_of_accounts_service import load_chart_of_accounts
from app.tenant_settings import (
    tenant_industry,
    tenant_onboarding_completed,
    tenant_setup_checklist_complete,
)

_CHECKLIST_DEFS: list[dict] = [
    {
        "id": "profile_name",
        "label": "Set your business name",
        "group": "Profile",
        "route": "/settings?tab=profile",
    },
    {
        "id": "profile_industry",
        "label": "Choose your industry",
        "group": "Profile",
        "route": "/settings?tab=profile",
    },
    {
        "id": "profile_country",
        "label": "Confirm business country",
        "group": "Profile",
        "route": "/settings?tab=profile",
    },
    {
        "id": "team_invite",
        "label": "Invite a team member",
        "group": "Team",
        "route": "/settings?tab=team",
        "optional": True,
    },
    {
        "id": "connect_mailbox",
        "label": "Connect an email mailbox",
        "group": "Integrations",
        "route": "/integrations",
    },
    {
        "id": "chart_of_accounts",
        "label": "Configure chart of accounts",
        "group": "Accounting",
        "route": "/settings?tab=coa",
    },
    {
        "id": "first_document",
        "label": "Upload your first document",
        "group": "Documents",
        "route": "/upload",
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
        coa = await load_chart_of_accounts(session, tenant_id)
        accounts = coa.get("accounts") if isinstance(coa, dict) else None
        return isinstance(accounts, list) and len(accounts) > 0
    if item_id == "first_document":
        count = (
            await session.execute(
                select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant_id)
            )
        ).scalar_one()
        return int(count or 0) > 0
    return False


async def build_setup_checklist_state(
    session: AsyncSession,
    *,
    tenant: Tenant,
    user_role: str,
    is_support_session: bool,
) -> SetupChecklistStateResponse:
    if tenant_setup_checklist_complete(tenant):
        return SetupChecklistStateResponse(complete=True, show=False, progress=100, items=[])

    if is_support_session or user_role not in ("admin", "super_admin"):
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
    all_required_done = all(i.done for i in required)
    complete = all_required_done

    show = not complete and tenant_onboarding_completed(tenant)

    return SetupChecklistStateResponse(
        complete=complete,
        show=show,
        progress=progress,
        items=items,
    )
