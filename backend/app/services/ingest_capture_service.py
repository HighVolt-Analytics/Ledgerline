"""Apply email capture rules at ingest time (before PDF parse).

Ingestion rules are an accept/skip gate only — they do not set workspace routing.
Routing is decided after OCR from document content (category rules / document type).
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import EmailCaptureRule, RuleBookConfigPayload
from app.services.audit_service import log_event
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.invoice_evaluation_service import load_config_for_tenant
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
    """Return the first matching ingestion rule, or None to skip the attachment."""
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
    """Record a matched ingestion rule; routing is applied after OCR, not here."""
    if config is None:
        config = await load_config_for_tenant(session, invoice.tenant_id)

    rule = evaluate_ingest_capture(email, attachment, config)
    if not rule:
        return None

    invoice.matched_rule_ids = json.dumps([f"ingest:{rule.id}"])
    # Clear any prior route so post-parse evaluation is not sticky from a previous run.
    invoice.route_target = None
    invoice.evaluation_status = None
    invoice.vendor_confidence = None

    await log_event(
        session,
        "ingest_capture_matched",
        invoice_id=invoice.id,
        detail={
            "rule_id": rule.id,
            "rule_name": rule.name,
            "tags": rule.action.tags,
            "message_id": email.message_id,
            "attachment": attachment.filename,
            "ingest_only": True,
        },
    )
    await session.flush()
    return rule
