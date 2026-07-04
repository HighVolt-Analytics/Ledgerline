"""Compile classifier AND/OR trees into LLM-readable recognition bullets."""

from __future__ import annotations

from typing import Any

from app.schemas.document_type import DocumentTypeDefinition, DocumentTypeClassifier

_FIELD_LABELS: dict[str, str] = {
    "document_heading": "Document heading",
    "document_text": "Document text",
    "attachment_name": "Attachment name",
    "email_sender": "Email sender",
    "email_subject": "Email subject",
    "vendor": "Vendor",
    "invoice_no": "Invoice number",
    "po_reference": "PO reference",
    "has_po_reference": "Has PO reference",
    "has_invoice_no": "Has invoice number",
    "has_total": "Has total amount",
    "has_heading_invoice": "Tax invoice heading",
    "has_heading_grn": "GRN / delivery heading",
    "has_heading_po": "Purchase order heading",
    "has_heading_credit_note": "Credit note heading",
    "has_heading_quote": "Quote heading",
    "has_heading_contract": "Contract heading",
    "is_commercial_invoice": "Commercial invoice",
}


def _field_label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " "))


def _condition_phrase(node: dict[str, Any]) -> str:
    field = str(node.get("field") or "")
    op = str(node.get("operator") or "equals")
    value = str(node.get("value") or "")
    label = _field_label(field)
    if field.startswith("has_") or field.startswith("is_"):
        if value.lower() == "true":
            return label
        if value.lower() == "false":
            return f"NOT {label}"
    if op == "contains":
        return f'{label} contains "{value}"'
    if op == "not_contains":
        return f'{label} does not contain "{value}"'
    if op == "equals":
        return f'{label} equals "{value}"'
    if op == "not_equals":
        return f'{label} does not equal "{value}"'
    if op == "starts_with":
        return f'{label} starts with "{value}"'
    if op == "ends_with":
        return f'{label} ends with "{value}"'
    return f"{label} {op} {value}"


def _group_phrase(node: dict[str, Any]) -> str:
    op = str(node.get("operator") or "AND").upper()
    children = node.get("children") or []
    parts: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "condition":
            parts.append(_condition_phrase(child))
        elif child.get("type") == "group":
            parts.append(f"({_group_phrase(child)})")
    if not parts:
        return ""
    joiner = " OR " if op == "OR" else " AND "
    return joiner.join(parts)


def compile_recognition_rules_text(classifier: DocumentTypeClassifier | None) -> str:
    if classifier is None or not classifier.enabled:
        return ""
    root = classifier.root if isinstance(classifier.root, dict) else {}
    phrase = _group_phrase(root).strip()
    if not phrase:
        return ""
    return f"Match rules: {phrase}"


def compile_catalogue_recognition(defn: DocumentTypeDefinition) -> str:
    parts: list[str] = []
    rules = compile_recognition_rules_text(defn.classifier)
    if rules:
        parts.append(rules)
    hint = (defn.llm_hint or "").strip()
    if hint:
        parts.append(hint)
    return " ".join(parts).strip()
