"""Apply email capture rules at ingest time (before PDF parse).

Ingestion rules are an accept/skip gate only — they do not set workspace routing.
Routing is decided after OCR from document content (category rules / document type).
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import (
    EmailCaptureAction,
    EmailCaptureRule,
    RuleBookConfigPayload,
    RuleCondition,
    RuleConditionGroup,
)
from app.services.audit.audit_service import log_event
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.rule_book.rule_engine import SampleEmail, match_email_capture_rule


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


DEFAULT_CATCH_ALL_CAPTURE_RULE_ID = "ec-default"
# UI / demo placeholder — treat as "any connected mailbox" at ingest time.
LEGACY_DEFAULT_MAILBOX = "accounts@acme-hospitality.com.au"


def _normalize_rule_mailbox(rule_mailbox: str, actual_mailbox: str) -> str:
    """Map legacy placeholder or wildcard to the mailbox being polled."""
    normalized = rule_mailbox.strip().lower()
    if normalized in {"", "*"}:
        return actual_mailbox
    if normalized == LEGACY_DEFAULT_MAILBOX.lower():
        return actual_mailbox
    return rule_mailbox


def _effective_capture_rules(
    config: RuleBookConfigPayload,
    actual_mailbox: str,
) -> list[EmailCaptureRule]:
    """Resolve rule mailbox filters against the connected mailbox being polled."""
    mailbox = actual_mailbox.strip().lower()
    return [
        rule.model_copy(update={"mailbox": _normalize_rule_mailbox(rule.mailbox, mailbox)})
        for rule in config.email_capture_rules
    ]


def default_catch_all_capture_rule(mailbox_email: str) -> EmailCaptureRule:
    """Synthetic rule used when no email capture rules are configured."""
    mailbox = mailbox_email.strip() or "inbox"
    return EmailCaptureRule(
        id=DEFAULT_CATCH_ALL_CAPTURE_RULE_ID,
        name="All mailbox attachments",
        enabled=True,
        priority=9999,
        mailbox=mailbox,
        root=RuleConditionGroup(
            type="group",
            operator="OR",
            children=[
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="contains",
                    value=".",
                ),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Purchase Management",
            tags=[],
        ),
    )


def _enabled_capture_rules(config: RuleBookConfigPayload) -> list[EmailCaptureRule]:
    return [rule for rule in config.email_capture_rules if rule.enabled]


def evaluate_ingest_capture(
    email: RawEmail,
    attachment: EmailAttachment,
    config: RuleBookConfigPayload,
) -> EmailCaptureRule | None:
    """Return the first matching ingestion rule, or None to skip the attachment."""
    if not _enabled_capture_rules(config):
        return default_catch_all_capture_rule(email.mailbox_email)
    sample = raw_email_to_sample_email(email, attachment)
    effective_rules = _effective_capture_rules(config, email.mailbox_email)
    return match_email_capture_rule(
        sample,
        effective_rules,
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
