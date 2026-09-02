"""Apply email capture rules at ingest time (before PDF parse).

Ingestion rules are an accept/skip gate only — they do not set workspace routing.
Routing is decided after OCR from document content (category rules / document type).
"""

from __future__ import annotations

import json
from typing import Any

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
from app.services.rule_book.rule_engine import (
    SampleEmail,
    diagnose_email_capture_match,
    match_email_capture_rule,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def raw_email_to_sample_email(email: RawEmail, attachment: EmailAttachment) -> SampleEmail:
    return SampleEmail(
        id=email.message_id,
        from_addr=email.sender or "",
        to=email.mailbox_email,
        subject=email.subject or "",
        body=email.body or "",
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


EMPLOYEE_BYPASS_CAPTURE_RULE_ID = "ec-employee-bypass"
DEFAULT_CATCH_ALL_CAPTURE_RULE_IDS = frozenset(
    {DEFAULT_CATCH_ALL_CAPTURE_RULE_ID, "ec-default"}
)
_CATCH_ALL_RULE_NAMES = frozenset(
    {
        "all mailbox attachments",
        "catch all",
        "catch-all",
        "all attachments",
    }
)


def infer_requires_employee_sender(rule: EmailCaptureRule) -> bool:
    """Derive employee-sender requirement from legacy route/id/name heuristics."""
    route = (rule.action.route_to or "").strip()
    if route == "Team Expenses":
        return True
    if (rule.id or "").strip() in DEFAULT_CATCH_ALL_CAPTURE_RULE_IDS:
        return True
    if (rule.id or "").strip() == EMPLOYEE_BYPASS_CAPTURE_RULE_ID:
        return True
    if (rule.name or "").strip().lower() in _CATCH_ALL_RULE_NAMES:
        return True
    return False


def capture_rule_requires_employee_sender(rule: EmailCaptureRule | None) -> bool:
    """True when ingest must also match an employee master email.

    Reads persisted ``requires_employee_sender`` when set; otherwise falls back to
    legacy route/id/name inference for rules saved before the field existed.
    """
    if rule is None:
        return False
    if rule.requires_employee_sender is not None:
        return rule.requires_employee_sender
    return infer_requires_employee_sender(rule)


def backfill_requires_employee_sender_on_rule_dict(rule: dict[str, Any]) -> dict[str, Any]:
    """Ensure JSON rule rows include requires_employee_sender when missing."""
    if not isinstance(rule, dict):
        return rule
    if rule.get("requires_employee_sender") is not None:
        return rule
    try:
        model = EmailCaptureRule.model_validate(rule)
    except Exception:
        return rule
    merged = dict(rule)
    merged["requires_employee_sender"] = infer_requires_employee_sender(model)
    return merged


def employee_bypass_capture_rule(mailbox_email: str = "*") -> EmailCaptureRule:
    """Default persisted employee-ingest rule template (Team Expenses, employee-gated at pipeline)."""
    mailbox = (mailbox_email or "*").strip() or "*"
    return EmailCaptureRule(
        id=EMPLOYEE_BYPASS_CAPTURE_RULE_ID,
        name="Employee registry attachments",
        enabled=True,
        priority=100,
        mailbox=mailbox,
        root=RuleConditionGroup(
            type="group",
            operator="OR",
            children=[
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="ends_with",
                    value=".pdf",
                ),
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="ends_with",
                    value=".jpg",
                ),
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="ends_with",
                    value=".jpeg",
                ),
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="ends_with",
                    value=".png",
                ),
                RuleCondition(
                    type="condition",
                    field="attachment_name",
                    operator="ends_with",
                    value=".docx",
                ),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Team Expenses",
            tags=[],
        ),
        requires_employee_sender=True,
    )


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


def ensure_email_capture_rules_in_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure the persisted employee-ingest rule exists for every tenant."""
    rules = data.get("email_capture_rules")
    if not isinstance(rules, list):
        rules = []
    merged = dict(data)
    if not any(
        isinstance(row, dict) and row.get("id") == EMPLOYEE_BYPASS_CAPTURE_RULE_ID for row in rules
    ):
        rules = [employee_bypass_capture_rule("*").model_dump(), *rules]
    merged["email_capture_rules"] = [
        backfill_requires_employee_sender_on_rule_dict(row) if isinstance(row, dict) else row
        for row in rules
    ]
    return merged


def _mailbox_mapping_summary(
    config: RuleBookConfigPayload,
    actual_mailbox: str,
) -> list[dict[str, str]]:
    """Show configured vs effective mailbox per enabled rule (for logs)."""
    effective = _effective_capture_rules(config, actual_mailbox)
    effective_by_id = {rule.id: rule for rule in effective}
    rows: list[dict[str, str]] = []
    for rule in _enabled_capture_rules(config):
        effective_rule = effective_by_id.get(rule.id)
        rows.append(
            {
                "rule_id": rule.id,
                "configured_mailbox": rule.mailbox,
                "effective_mailbox": effective_rule.mailbox if effective_rule else rule.mailbox,
            }
        )
    return rows


def log_ingest_capture_decision(
    email: RawEmail,
    attachment: EmailAttachment,
    config: RuleBookConfigPayload,
    *,
    matched_rule: EmailCaptureRule | None,
) -> None:
    """Structured log for ingest-time email capture rule evaluation."""
    base = {
        "message_id": email.message_id,
        "mailbox": email.mailbox_email,
        "sender": email.sender,
        "subject": email.subject,
        "attachment": attachment.filename,
    }
    enabled = _enabled_capture_rules(config)
    if not enabled:
        logger.info(
            "ingest_capture_decision",
            outcome="zero_rules_enabled",
            enabled_rule_count=0,
            **base,
        )
        return

    sample = raw_email_to_sample_email(email, attachment)
    effective_rules = _effective_capture_rules(config, email.mailbox_email)
    diagnosis = diagnose_email_capture_match(
        sample,
        effective_rules,
        mailbox=email.mailbox_email,
    )
    diagnosis_payload = {
        key: value
        for key, value in diagnosis.items()
        if key not in {"matched_rule_id", "matched_rule_name"}
    }
    if matched_rule:
        logger.info(
            "ingest_capture_decision",
            outcome="matched",
            matched_rule_id=matched_rule.id,
            matched_rule_name=matched_rule.name,
            mailbox_mappings=_mailbox_mapping_summary(config, email.mailbox_email),
            **diagnosis_payload,
        )
    else:
        logger.warning(
            "ingest_capture_decision",
            outcome="no_match",
            mailbox_mappings=_mailbox_mapping_summary(config, email.mailbox_email),
            **diagnosis,
        )


def evaluate_ingest_capture(
    email: RawEmail,
    attachment: EmailAttachment,
    config: RuleBookConfigPayload,
) -> EmailCaptureRule | None:
    """Return the first matching ingestion rule, or None to skip the attachment."""
    if not _enabled_capture_rules(config):
        return None
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
