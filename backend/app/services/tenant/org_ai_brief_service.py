"""Load and persist tenant org AI brief (org_context slice of rule book config)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.org_ai_brief import OrgAiBriefResponse, UpdateOrgAiBriefRequest
from app.schemas.rule_book_config import OrgContextConfig, validate_rule_book_config_payload
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config


def org_context_from_config_dict(raw: dict[str, Any]) -> OrgContextConfig | None:
    payload = validate_rule_book_config_payload(raw)
    return payload.org_context


async def load_org_ai_brief(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> OrgAiBriefResponse:
    raw = await load_rule_book_config_dict(session, tenant_id)
    return OrgAiBriefResponse.from_org_context(org_context_from_config_dict(raw))


async def save_org_ai_brief(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpdateOrgAiBriefRequest,
    *,
    updated_by_user_id: int | None = None,
) -> OrgAiBriefResponse:
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    merged = payload.model_dump()
    merged["org_context"] = body.to_org_context().model_dump(by_alias=False)
    updated = validate_rule_book_config_payload(merged)
    await save_rule_book_config(
        session,
        updated,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
    return OrgAiBriefResponse.from_org_context(updated.org_context)


async def sync_org_legal_name_on_tenant_rename(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    old_name: str,
    new_name: str,
    updated_by_user_id: int | None = None,
) -> None:
    """Keep org AI brief legal name aligned when the tenant display name changes."""
    new_clean = new_name.strip()
    old_clean = old_name.strip()
    if not new_clean or new_clean.lower() == old_clean.lower():
        return

    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    org = payload.org_context
    if org is None:
        return

    legal = (org.legal_name or "").strip()
    if legal and legal.lower() != old_clean.lower():
        return

    merged = payload.model_dump()
    merged["org_context"] = org.model_copy(update={"legal_name": new_clean}).model_dump(
        by_alias=False
    )
    updated = validate_rule_book_config_payload(merged)
    await save_rule_book_config(
        session,
        updated,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
