"""Email ingestion rules API — managed from Upload → Email setup, not Rule Book UI."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox

from app.schemas.rule_book_config import (
    EmailCaptureAction,
    EmailCaptureRule,
    RuleBookConfigPayload,
    RuleConditionGroup,
    validate_rule_book_config_for_save,
)
from app.services.ingest.email_capture_rule_validation import (
    validate_email_capture_rules_specificity,
    validate_email_capture_rules_warnings_by_id,
)
from app.services.ingest.ingest_capture_service import infer_requires_employee_sender
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book.rule_book_ingest_stats import (
    attach_email_capture_ingest_stats,
    load_email_capture_ingest_stats,
    strip_email_capture_volatile_stats,
)
from app.services.rule_book.rule_book_save_buffer import (
    flush_rule_book_save_buffer,
    schedule_rule_book_save,
)


async def _connected_mailbox_emails(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> set[str]:
    rows = (
        await session.execute(
            select(ConnectedMailbox.email).where(ConnectedMailbox.tenant_id == tenant_id)
        )
    ).scalars().all()
    return {str(email).strip().lower() for email in rows if email}


async def load_email_ingestion_rules_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    attach_stats: bool = True,
) -> dict[str, Any]:
    data = await load_rule_book_config_dict(session, tenant_id)
    rules = data.get("email_capture_rules") or []
    payload: dict[str, Any] = {"email_capture_rules": rules}
    if attach_stats:
        payload = await attach_email_capture_ingest_stats(session, tenant_id, payload)
    connected = await _connected_mailbox_emails(session, tenant_id)
    payload["connected_mailbox_emails"] = sorted(connected)
    try:
        parsed = [
            EmailCaptureRule.model_validate(row) if isinstance(row, dict) else row
            for row in payload.get("email_capture_rules") or []
        ]
        payload["rule_warnings"] = validate_email_capture_rules_warnings_by_id(
            parsed,
            connected_mailbox_emails=connected,
        )
    except ValidationError:
        payload["rule_warnings"] = {}
    return payload


def normalize_email_capture_rules_for_save(rules: list[EmailCaptureRule]) -> list[EmailCaptureRule]:
    """Ensure requires_employee_sender is persisted on every rule."""
    normalized: list[EmailCaptureRule] = []
    for rule in rules:
        requires = rule.requires_employee_sender
        if requires is None:
            requires = infer_requires_employee_sender(rule)
        normalized.append(rule.model_copy(update={"requires_employee_sender": requires}))
    return normalized


async def load_email_ingestion_stats_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    stats = await load_email_capture_ingest_stats(session, tenant_id)
    return {
        "ingest_stats": {
            rule_id: {
                "matched_count": row.matched_count,
                "last_matched": row.last_matched,
            }
            for rule_id, row in stats.items()
        }
    }


async def save_email_ingestion_rules(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    rules: list[EmailCaptureRule],
    *,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None,
) -> tuple[RuleBookConfigPayload, list[str]]:
    warnings = validate_email_capture_rules_specificity(rules)
    normalized = normalize_email_capture_rules_for_save(rules)
    stored = await load_rule_book_config_dict(session, tenant_id)
    stored["email_capture_rules"] = [rule.model_dump() for rule in normalized]
    strip_email_capture_volatile_stats(stored)
    payload = validate_rule_book_config_for_save(stored)
    after_raw = payload.model_dump()
    await schedule_rule_book_save(
        tenant_id=tenant_id,
        payload=payload,
        after_raw=after_raw,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
        db=session,
        remap_invoices=False,
    )
    await flush_rule_book_save_buffer(
        tenant_id=tenant_id,
        db=session,
        remap_invoices=False,
    )
    return payload, warnings


async def load_recent_skips_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    mailbox: str,
) -> dict[str, Any]:
    from app.services.ingest.email_ingestion_recent_skips_service import (
        load_recent_email_skips_for_mailbox,
    )

    skips = await load_recent_email_skips_for_mailbox(session, tenant_id, mailbox)
    return {"mailbox": mailbox, "skips": skips}


def build_preview_capture_rule(
    *,
    mailbox: str,
    root: RuleConditionGroup,
    rule_name: str,
) -> EmailCaptureRule:
    return EmailCaptureRule(
        id="preview",
        name=rule_name,
        enabled=True,
        priority=1,
        mailbox=mailbox,
        root=root,
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Purchase Management",
            tags=[],
        ),
    )


def validation_http_detail(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return str(exc)
    return str(exc)
