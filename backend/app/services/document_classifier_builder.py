"""Build document-type classifier trees from recognition signals (parity with frontend)."""

from __future__ import annotations

from typing import Any

from app.schemas.document_type import DocumentTypeClassifier

RecognitionSignalId = str
ClassifierLayout = str

WEAK_SIGNALS = frozenset({"has_po_reference", "has_invoice_number", "has_total_amount"})

SIGNAL_PICK_GROUPS: tuple[tuple[RecognitionSignalId, ...], ...] = (
    ("heading_invoice", "text_invoice", "filename_invoice"),
    ("heading_po", "text_po", "filename_po"),
    ("heading_grn", "text_grn", "filename_grn"),
    ("heading_contract", "text_contract", "filename_contract"),
    ("text_credit_note", "filename_credit_note"),
    ("text_debit_note", "filename_debit_note"),
    ("text_proforma", "filename_proforma"),
    ("text_claim", "filename_claim"),
    ("text_quote", "filename_quote"),
    ("text_tax_notice", "filename_tax_notice"),
    ("text_bank_change", "filename_bank_change"),
    ("text_freight", "filename_freight"),
    ("text_import", "filename_import"),
    ("text_intercompany", "filename_intercompany"),
    ("text_terms", "text_governing_law", "text_signed_behalf"),
)

SUPPORTING_GUARDS: list[dict[str, Any]] = [
    {"type": "condition", "field": "has_invoice_no", "operator": "equals", "value": "false"},
    {"type": "condition", "field": "is_commercial_invoice", "operator": "equals", "value": "false"},
]

_SIGNAL_CONDITIONS: dict[RecognitionSignalId, dict[str, Any]] = {
    "heading_po": {"field": "has_heading_po", "operator": "equals", "value": "true"},
    "text_po": {"field": "document_text", "operator": "regex", "value": "(?i)purchase order"},
    "filename_po": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)purchase[_-]?order|(^|[-_/])po([-_.]|$)",
    },
    "heading_grn": {"field": "has_heading_grn", "operator": "equals", "value": "true"},
    "text_grn": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(goods\\s+receipt|delivery\\s+(note|docket)|\\bGRN\\b)",
    },
    "filename_grn": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)grn|goods[_-]?receipt|delivery[_-]?note",
    },
    "heading_contract": {"field": "has_heading_contract", "operator": "equals", "value": "true"},
    "text_contract": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(\\bcontract\\b|docusign|master service agreement|terms and conditions)",
    },
    "filename_contract": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(contract|lease|sow|statement[_-]?of[_-]?work|rate[_-]?card)",
    },
    "text_terms": {"field": "document_text", "operator": "contains", "value": "terms and conditions"},
    "text_governing_law": {"field": "document_text", "operator": "contains", "value": "governing law"},
    "text_signed_behalf": {
        "field": "document_text",
        "operator": "contains",
        "value": "signed for and on behalf",
    },
    "heading_invoice": {"field": "has_heading_invoice", "operator": "equals", "value": "true"},
    "text_invoice": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(tax\\s+invoice|commercial\\s+invoice|billing\\s+summary|invoice\\s+no|invoice\\s+number)\\b",
    },
    "filename_invoice": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(?:^|[-_/])(?:inv|invoice|tax[_-]?inv)(?:[-_.]|$)",
    },
    "text_credit_note": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(credit\\s+note|creditmemo|credit_memo)",
    },
    "filename_credit_note": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(credit[_-]?note|creditmemo|credit_memo)",
    },
    "text_debit_note": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(debit\\s+note|debitmemo|debit_memo)",
    },
    "filename_debit_note": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(debit[_-]?note|debitmemo|debit_memo)",
    },
    "text_proforma": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)",
    },
    "filename_proforma": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(pro[\\s_-]?forma|advance[\\s_-]?request)",
    },
    "text_claim": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(expense[_-]?claim|reimburse|team\\s+lunch|\\bmeal\\b)",
    },
    "filename_claim": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(expense[_-]?claim|claim[_-]?receipt|team[_-]?meal|reimburse)",
    },
    "text_quote": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(quote|quotation|estimate|proposal)\\b",
    },
    "filename_quote": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(quote|quotation|estimate|proposal)",
    },
    "text_tax_notice": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)\\b(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)\\b",
    },
    "filename_tax_notice": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(ato|tax[_-]?office|tax[_-]?notice|compliance[_-]?notice)",
    },
    "text_bank_change": {
        "field": "document_text",
        "operator": "regex",
        "value": "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)",
    },
    "filename_bank_change": {
        "field": "attachment_name",
        "operator": "regex",
        "value": "(?i)(bank[_-]?detail|change[_-]?of[_-]?bank)",
    },
    "has_po_reference": {"field": "has_po_reference", "operator": "equals", "value": "true"},
    "has_invoice_number": {"field": "has_invoice_no", "operator": "equals", "value": "true"},
    "has_total_amount": {"field": "has_total", "operator": "equals", "value": "true"},
}


def _cond(signal_id: RecognitionSignalId) -> dict[str, Any]:
    spec = _SIGNAL_CONDITIONS.get(signal_id)
    if spec is None:
        return {"type": "condition", "field": "document_text", "operator": "contains", "value": ""}
    return {"type": "condition", **spec}


def _or_group(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "group", "operator": "OR", "children": children}


def _and_group(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "group", "operator": "AND", "children": children}


def build_classifier_root_grouped(signal_ids: list[RecognitionSignalId]) -> dict[str, Any]:
    available = set(signal_ids)
    and_children: list[dict[str, Any]] = []
    used: set[RecognitionSignalId] = set()

    for group in SIGNAL_PICK_GROUPS:
        matched = [signal_id for signal_id in group if signal_id in available]
        if not matched:
            continue
        used.update(matched)
        if len(matched) == 1:
            and_children.append(_cond(matched[0]))
        else:
            and_children.append(_or_group([_cond(signal_id) for signal_id in matched]))

    ungrouped = [signal_id for signal_id in signal_ids if signal_id not in used and signal_id not in WEAK_SIGNALS]
    if len(ungrouped) == 1:
        and_children.append(_cond(ungrouped[0]))
    elif len(ungrouped) > 1:
        and_children.append(_or_group([_cond(signal_id) for signal_id in ungrouped]))

    for signal_id in signal_ids:
        if signal_id in WEAK_SIGNALS:
            and_children.append(_cond(signal_id))

    if not and_children:
        return {"type": "group", "operator": "AND", "children": []}
    if len(and_children) == 1:
        return and_children[0]
    return _and_group(and_children)


def build_classifier_root(signal_ids: list[RecognitionSignalId], layout: ClassifierLayout) -> dict[str, Any]:
    if not signal_ids:
        return {"type": "group", "operator": "AND", "children": []}

    if layout == "grouped":
        return build_classifier_root_grouped(signal_ids)

    leaves = [_cond(signal_id) for signal_id in signal_ids]
    if layout == "all_signals":
        return _and_group(leaves)
    if layout == "supporting_doc":
        identity = build_classifier_root_grouped(signal_ids)
        if identity.get("type") == "condition":
            identity = _or_group([identity])
        return _and_group([identity, *SUPPORTING_GUARDS])
    return _or_group(leaves)


def build_classifier_from_signals(
    signal_ids: list[RecognitionSignalId],
    layout: ClassifierLayout,
    *,
    priority: int = 100,
    confidence: float = 0.85,
    enabled: bool = True,
) -> DocumentTypeClassifier:
    return DocumentTypeClassifier(
        enabled=enabled and bool(signal_ids),
        priority=priority,
        confidence=confidence,
        root=build_classifier_root(signal_ids, layout),
    )


def eval_recognition_signal(ctx: object, signal_id: RecognitionSignalId) -> bool:
    """True when a single recognition signal's classifier condition matches the sample."""
    from app.services.document_type_rule_engine import _document_field
    from app.services.rule_engine import _match_value

    spec = _SIGNAL_CONDITIONS.get(signal_id)
    if spec is None:
        return False
    haystack = _document_field(ctx, str(spec["field"]))
    return _match_value(
        haystack,
        str(spec["operator"]),
        str(spec["value"]),
    )


def filter_verified_recognition_signals(
    ctx: object,
    signals: frozenset[RecognitionSignalId] | set[RecognitionSignalId],
) -> frozenset[RecognitionSignalId]:
    """Drop detection-only false positives before building a sample classifier."""
    verified = {signal_id for signal_id in signals if eval_recognition_signal(ctx, signal_id)}
    return frozenset(verified)
