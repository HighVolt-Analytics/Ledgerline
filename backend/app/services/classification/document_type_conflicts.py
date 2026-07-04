"""Detect conflicting OCR signals before routing a document type."""

from __future__ import annotations

from app.services.classification.document_type_rule_engine import DocumentClassifierContext

CONFLICT_PENALTY_EACH = 0.08
CONFLICT_PENALTY_MAX = 0.35


def detect_signal_conflicts(ctx: DocumentClassifierContext) -> list[str]:
    """Return human-readable conflicts when headings and fields disagree."""
    conflicts: list[str] = []

    if ctx.has_heading_contract == "true" and ctx.has_heading_invoice == "true":
        conflicts.append("Conflicting headings: contract and invoice")

    if ctx.has_heading_po == "true" and ctx.has_heading_invoice == "true":
        conflicts.append("Conflicting headings: purchase order and invoice")

    if ctx.has_heading_grn == "true" and ctx.has_heading_invoice == "true":
        conflicts.append("Conflicting headings: goods receipt and invoice")

    if ctx.has_heading_po == "true" and ctx.has_invoice_no == "true":
        conflicts.append("Purchase order heading with invoice number present")

    if (
        ctx.has_heading_grn == "true"
        and ctx.has_invoice_no == "true"
        and ctx.has_total == "true"
    ):
        conflicts.append("Goods receipt heading with invoice-like number and total")

    if (
        ctx.has_heading_contract == "true"
        and ctx.has_invoice_no == "true"
        and ctx.has_total == "true"
    ):
        conflicts.append("Contract heading with invoice-like fields present")

    if ctx.has_heading_quote == "true" and ctx.has_total == "true":
        conflicts.append("Quote heading with monetary total present")

    if (
        ctx.has_heading_po == "true"
        and ctx.has_po_reference == "false"
        and ctx.has_total == "true"
        and ctx.has_invoice_no == "false"
    ):
        conflicts.append("Purchase order heading without PO reference but with total amount")

    return conflicts


def conflict_confidence_penalty(conflicts: list[str]) -> float:
    if not conflicts:
        return 0.0
    return min(CONFLICT_PENALTY_MAX, len(conflicts) * CONFLICT_PENALTY_EACH)
