"""Apply email capture rules at ingest time (before PDF parse)."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import EmailCaptureRule, RuleBookConfigPayload
from app.services.audit_service import log_event
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.invoice_evaluation_service import (
    EVAL_NEEDS_REVIEW,
    load_config_for_org,
)
from app.services.rule_engine import SampleEmail, match_email_capture_rule


def raw_email_to_sample_email(email: RawEmail, attachment: EmailAttachment) -> SampleEmail:
    return SampleEmail(
        id=email.message_id,
        from_addr=email.sender or "",
        to=email.mailbox_email,
        subject=email.subject or "",
        body="",
        attachment_name=attachment.filename,
        attachment_mime=attachment.content_type,
    )


def evaluate_ingest_capture(
    email: RawEmail,
    attachment: EmailAttachment,
    config: RuleBookConfigPayload,
) -> EmailCaptureRule | None:
    sample = raw_email_to_sample_email(email, attachment)
    return match_email_capture_rule(
        sample,
        config.email_capture_rules,
        mailbox=email.mailbox_email,
    )


async def apply_ingest_capture(
    session: AsyncSession,
    invoice: Invoice,
    email: RawEmail,
    attachment: EmailAttachment,
    *,
    config: RuleBookConfigPayload | None = None,
) -> EmailCaptureRule | None:
    """Set early route_target and matched_rule_ids from email capture rules."""
    if config is None:
        config = load_config_for_org(invoice.org_id)

    rule = evaluate_ingest_capture(email, attachment, config)
    if not rule:
        return None

    invoice.route_target = rule.action.route_to
    invoice.matched_rule_ids = json.dumps([f"email:{rule.id}"])
    invoice.evaluation_status = EVAL_NEEDS_REVIEW
    invoice.vendor_confidence = 0.0

    await log_event(
        session,
        "ingest_capture_matched",
        invoice_id=invoice.id,
        detail={
            "rule_id": rule.id,
            "rule_name": rule.name,
            "route_to": rule.action.route_to,
            "tags": rule.action.tags,
            "message_id": email.message_id,
            "attachment": attachment.filename,
        },
    )
    await session.flush()
    return rule
