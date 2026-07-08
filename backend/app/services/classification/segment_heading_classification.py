"""Classify split PDF segments using detected page heading kinds."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from typing import TYPE_CHECKING

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.document_heading_utils import HeadingKind, infer_page_document_kind
from app.services.classification.document_type_rule_engine import (
    build_document_classifier_context,
    list_configured_document_type_matches,
)
from app.services.invoice.invoice_data import InvoiceData, ParseConfidence
from app.services.rule_book.rule_engine import eval_condition_group_generic

if TYPE_CHECKING:
    from app.services.classification.document_type_classifier import DocumentTypeClassification

INVOICE_LIKE_KINDS = frozenset(
    {
        "invoice",
        "tax_invoice",
        "commercial_invoice",
        "proforma",
        "credit_note",
    }
)

# Tokens used to match org catalogue rows (short title, classifier regex, etc.).
HEADING_KIND_TOKENS: dict[str, tuple[str, ...]] = {
    "commercial_invoice": ("commercial invoice", "commercial inv"),
    "tax_invoice": ("tax invoice",),
    "invoice": ("invoice",),
    "packing_list": ("packing list", "weight list", "packing"),
    "certificate_of_origin": ("certificate of origin", "origin certificate", "coo"),
    "transport_doc": ("hawb", "mawb", "air waybill", "bill of lading", "awb", "b/l"),
    "customs_permit": (
        "cargo clearance permit",
        "customs permit",
        "customs entry",
        "import declaration",
        "clearance permit",
    ),
    "purchase_order": ("purchase order", " po "),
    "grn": ("goods receipt", "grn", "delivery note", "delivery docket"),
    "credit_note": ("credit note", "debit note"),
    "quote": ("quotation", "quote", "estimate"),
    "contract": ("contract", "sow", "statement of work", "rate card", "agreement"),
    "statement": ("statement of account", "vendor statement"),
    "remittance": ("remittance",),
    "proforma": ("pro forma", "proforma"),
    "timesheet": ("timesheet", "time sheet"),
}


def resolve_segment_heading_kind(
    *,
    document_text: str | None,
    segment_heading_kind: HeadingKind | None = None,
) -> HeadingKind | None:
    if segment_heading_kind:
        return segment_heading_kind
    return infer_page_document_kind(document_text or "")


def _definition_metadata_blob(definition: DocumentTypeDefinition) -> str:
    parts = [
        definition.short_title or "",
        definition.title or "",
        definition.llm_prompt or "",
        " ".join(definition.extraction or []),
    ]
    return " ".join(parts).lower()


def _classifier_document_text_blob(definition: DocumentTypeDefinition) -> str:
    chunks: list[str] = []

    def walk(node: dict[str, Any] | None) -> None:
        if not node:
            return
        if node.get("type") == "condition" and node.get("field") == "document_text":
            value = node.get("value")
            if isinstance(value, str) and value.strip():
                chunks.append(value.lower())
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(definition.classifier.root)
    return " ".join(chunks)


def score_document_type_for_heading(
    definition: DocumentTypeDefinition,
    heading_kind: HeadingKind,
) -> float:
    tokens = HEADING_KIND_TOKENS.get(heading_kind, ())
    if not tokens or not definition.enabled:
        return 0.0

    metadata = _definition_metadata_blob(definition)
    classifier_text = _classifier_document_text_blob(definition)
    best = 0.0

    for token in tokens:
        token = token.strip().lower()
        if not token:
            continue
        if token in (definition.short_title or "").lower():
            best = max(best, 1.0)
            continue
        if token in metadata:
            best = max(best, 0.82)
        if token in classifier_text:
            best = max(best, 0.88)
        for part in re.split(r"[\s/·]+", metadata):
            if part and token == part:
                best = max(best, 0.95)

    return best


def _classifier_field(ctx, field: str) -> str:
    from app.services.classification.document_type_rule_engine import _document_field

    return _document_field(ctx, field)


def classifier_match_relies_on_invoice_number(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> bool:
    """True when the classifier only matches because an invoice number is present."""
    classifier = definition.classifier
    if not classifier.enabled or not classifier.root:
        return False

    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    if not eval_condition_group_generic(
        classifier.root,
        field_resolver=lambda field, _ctx=ctx: _classifier_field(_ctx, field),
    ):
        return False

    no_number_ctx = replace(
        build_document_classifier_context(
            invoice=invoice,
            parsed=replace(parsed, invoice_no=None),
        ),
        invoice_no="",
        has_invoice_no="false",
    )

    still_matches = eval_condition_group_generic(
        classifier.root,
        field_resolver=lambda field, _ctx=no_number_ctx: _classifier_field(_ctx, field),
    )
    return not still_matches


_TRANSACTIONAL_PLAYBOOK_PROFILES = frozenset(
    {"po_goods", "po_services", "direct_expense", "ar_goods"}
)
_SUPPORTING_DOC_HEADING_KINDS = frozenset(
    {"certificate_of_origin", "customs_permit", "packing_list", "transport_doc"}
)


def heading_conflicts_with_definition(
    heading_kind: HeadingKind,
    definition: DocumentTypeDefinition,
) -> bool:
    metadata_score = score_document_type_for_heading(definition, heading_kind)
    if metadata_score >= 0.82:
        return False

    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )

    if heading_kind in _SUPPORTING_DOC_HEADING_KINDS:
        if effective_playbook_profile(definition) in _TRANSACTIONAL_PLAYBOOK_PROFILES:
            return True

    meta = _definition_metadata_blob(definition)
    if heading_kind == "transport_doc" and any(
        token in meta for token in ("contract", "sow", "lease", "rate card")
    ):
        return True
    if heading_kind == "certificate_of_origin" and "coo" not in meta and "origin" not in meta:
        if any(token in meta for token in ("contract", "sow", "lease")):
            return True
    if heading_kind in {"packing_list", "customs_permit", "transport_doc"}:
        if "coo" in meta and heading_kind != "certificate_of_origin":
            return True
    if heading_kind == "commercial_invoice" and "coo" in meta and "commercial" not in meta:
        return True
    return False


def classify_from_segment_heading(
    *,
    heading_kind: HeadingKind | None,
    document_types: Sequence[DocumentTypeDefinition],
    invoice: Invoice,
    parsed: InvoiceData,
    parse_confidence: ParseConfidence | None = None,
) -> "DocumentTypeClassification | None":
    """Pick a DT-xx row when the split-page heading aligns with catalogue metadata."""
    if heading_kind is None:
        return None

    from app.services.classification.document_type_classifier import DocumentTypeClassification

    scored: list[tuple[DocumentTypeDefinition, float]] = []
    for definition in document_types:
        if not definition.enabled:
            continue
        score = score_document_type_for_heading(definition, heading_kind)
        if score >= 0.82:
            scored.append((definition, score))

    if not scored:
        return None

    definition, score = max(
        scored,
        key=lambda item: (item[1], -item[0].classifier.priority),
    )
    from app.services.classification.document_type_scoring_service import score_document_type_definition

    breakdown = score_document_type_definition(
        definition,
        invoice=invoice,
        parsed=parsed,
        rule_strength=min(1.0, 0.78 + score * 0.15),
        parse_confidence=parse_confidence,
    )
    return DocumentTypeClassification(
        definition.code,
        breakdown.confidence,
        f"Segment heading ({heading_kind}) matched document type catalogue",
        min_route_confidence=breakdown.min_route_confidence,
        score_breakdown=breakdown,
    )


def filter_configured_matches_for_heading(
    matches: list[tuple[DocumentTypeDefinition, str]],
    *,
    heading_kind: HeadingKind | None,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[tuple[DocumentTypeDefinition, str]]:
    if heading_kind is None:
        return matches

    filtered: list[tuple[DocumentTypeDefinition, str]] = []
    for definition, source in matches:
        if heading_conflicts_with_definition(heading_kind, definition):
            continue
        if heading_kind not in INVOICE_LIKE_KINDS and classifier_match_relies_on_invoice_number(
            definition,
            invoice=invoice,
            parsed=parsed,
        ):
            continue
        filtered.append((definition, source))
    return filtered


def parse_segment_heading_kind(raw: object) -> HeadingKind | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value in HEADING_KIND_TOKENS:
        return value  # type: ignore[return-value]
    return None


def segment_heading_kind_from_audit_detail(detail: object) -> HeadingKind | None:
    if detail is None:
        return None
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            return None
    if not isinstance(detail, dict):
        return None
    return parse_segment_heading_kind(detail.get("heading_kind"))


async def load_segment_heading_kind_from_audit(session, invoice_id: int) -> HeadingKind | None:
    from sqlalchemy import select

    from app.models.audit import AuditLog

    row = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.event == "pdf_segmented",
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return segment_heading_kind_from_audit_detail(row.detail)


def list_heading_aware_document_type_matches(
    document_types: list[DocumentTypeDefinition],
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    heading_kind: HeadingKind | None = None,
) -> list[tuple[DocumentTypeDefinition, str]]:
    matches = list_configured_document_type_matches(
        document_types,
        invoice=invoice,
        parsed=parsed,
    )
    resolved = resolve_segment_heading_kind(
        document_text=parsed.document_text,
        segment_heading_kind=heading_kind,
    )
    return filter_configured_matches_for_heading(
        matches,
        heading_kind=resolved,
        invoice=invoice,
        parsed=parsed,
    )
