"""Evaluate document-type recognition rules against OCR text (Rule Book editor)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_rule_engine import (
    _document_field,
    build_document_classifier_context,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.rule_engine import classifier_has_actionable_conditions, eval_condition_group_generic


@dataclass(frozen=True)
class RecognitionTestResult:
    matches: bool
    match_rules_passed: bool
    exclude_rules_passed: bool
    summary: str
    classifier_enabled: bool


def _split_match_exclude_roots(
    root: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Best-effort split AND(match, exclude) compiled from match-rules UI."""
    if root.get("type") != "group" or root.get("operator") != "AND":
        return root, None
    children = root.get("children") or []
    if len(children) == 2 and all(isinstance(c, dict) for c in children):
        return children[0], children[1]
    if len(children) == 1 and isinstance(children[0], dict):
        # Keep AND wrapper so single-condition trees still evaluate as groups.
        return root, None
    if not children:
        return None, None
    return root, None


def _eval_root(root: dict[str, Any] | None, ctx: object) -> bool:
    if root is None:
        return True
    if root.get("type") == "condition":
        from app.services.rule_book.rule_engine import _match_value

        value = _document_field(ctx, str(root.get("field", "")))
        return _match_value(
            value,
            str(root.get("operator", "")),
            str(root.get("value", "")),
            case_sensitive=root.get("case_sensitive"),
        )
    return eval_condition_group_generic(
        root,
        field_resolver=lambda field, _ctx=ctx: _document_field(_ctx, field),
    )


def evaluate_document_type_recognition(
    draft: DocumentTypeDefinition,
    *,
    document_text: str,
    document_heading: str = "",
    email_sender: str = "",
    attachment_name: str = "",
) -> RecognitionTestResult:
    classifier = draft.classifier
    if not classifier.enabled:
        return RecognitionTestResult(
            matches=False,
            match_rules_passed=False,
            exclude_rules_passed=True,
            summary="Classifier is disabled — enable recognition to test.",
            classifier_enabled=False,
        )

    root = classifier.root if isinstance(classifier.root, dict) else {}
    if not classifier_has_actionable_conditions(root):
        return RecognitionTestResult(
            matches=False,
            match_rules_passed=False,
            exclude_rules_passed=True,
            summary="Add at least one match or exclusion rule.",
            classifier_enabled=True,
        )

    invoice = Invoice(
        id=0,
        tenant_id=uuid.UUID(int=0),
        status=InvoiceStatus.PENDING,
        email_sender=email_sender.strip() or None,
        email_attachment_name=attachment_name.strip() or None,
        document_text=document_text.strip() or None,
        document_heading=document_heading.strip() or None,
    )
    parsed = InvoiceData(
        document_text=document_text.strip(),
        document_heading=document_heading.strip() or None,
    )
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)

    match_root, exclude_root = _split_match_exclude_roots(root)
    match_ok = _eval_root(match_root, ctx)
    exclude_ok = _eval_root(exclude_root, ctx)
    matches = match_ok and exclude_ok

    if matches:
        summary = f"Rules match — would classify as {draft.code.strip().upper()}."
    elif not match_ok:
        summary = "Match rules did not pass for this text."
    else:
        summary = "Exclusion rules triggered — this text is excluded for this type."

    return RecognitionTestResult(
        matches=matches,
        match_rules_passed=match_ok,
        exclude_rules_passed=exclude_ok,
        summary=summary,
        classifier_enabled=True,
    )
