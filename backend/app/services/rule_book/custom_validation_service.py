"""Evaluate user-defined field validation rules at invoice validation time."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.invoice import Invoice
from app.schemas.custom_validation_rule import CustomValidationRule
from app.services.classification.document_type_field_checks import field_is_absent, field_is_present
from app.services.classification.document_type_rule_engine import (
    build_document_classifier_context,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.validator import ValidationResult


def _numeric_field_value(
    field_key: str,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> Decimal | None:
    key = field_key.strip().lower()
    mapping: dict[str, object | None] = {
        "total": parsed.total if parsed.total is not None else invoice.total,
        "subtotal": parsed.subtotal if parsed.subtotal is not None else invoice.subtotal,
        "gst": parsed.gst if parsed.gst is not None else invoice.gst,
    }
    raw = mapping.get(key)
    if raw is None:
        for source in (parsed, invoice):
            if hasattr(source, key):
                raw = getattr(source, key, None)
                if raw is not None:
                    break
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _text_field_value(
    field_key: str,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx,
) -> str:
    key = field_key.strip().lower()
    if key == "document_text":
        return (parsed.document_text or invoice.document_text or "").strip()
    if key == "email_subject":
        return (invoice.email_subject or "").strip()
    if field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
        for source in (parsed, invoice):
            if hasattr(source, key):
                val = getattr(source, key, None)
                if val is not None and str(val).strip():
                    return str(val).strip()
    return ""


def evaluate_custom_validation_rule(
    rule: CustomValidationRule,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> ValidationResult:
    rule_id = f"VR-CUSTOM-{rule.id}"
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    op = rule.operator

    if op == "present":
        ok = field_is_present(rule.field, invoice=invoice, parsed=parsed, ctx=ctx)
        if ok:
            return ValidationResult(rule_id, True, f"{rule.name}: field present", severity=rule.severity)
        return ValidationResult(rule_id, False, f"{rule.name}: field '{rule.field}' is missing", severity=rule.severity)

    if op == "absent":
        ok = field_is_absent(rule.field, invoice=invoice, parsed=parsed, ctx=ctx)
        if ok:
            return ValidationResult(rule_id, True, f"{rule.name}: field absent as required", severity=rule.severity)
        return ValidationResult(rule_id, False, f"{rule.name}: field '{rule.field}' must be absent", severity=rule.severity)

    haystack = _text_field_value(rule.field, invoice=invoice, parsed=parsed, ctx=ctx).lower()
    needle = rule.value.strip().lower()

    if op == "contains":
        if needle and needle in haystack:
            return ValidationResult(rule_id, True, f"{rule.name}: text match OK", severity=rule.severity)
        return ValidationResult(
            rule_id,
            False,
            f"{rule.name}: '{rule.field}' must contain '{rule.value}'",
            severity=rule.severity,
        )

    if op == "not_contains":
        if not needle or needle not in haystack:
            return ValidationResult(rule_id, True, f"{rule.name}: excluded text not found", severity=rule.severity)
        return ValidationResult(
            rule_id,
            False,
            f"{rule.name}: '{rule.field}' must not contain '{rule.value}'",
            severity=rule.severity,
        )

    actual = _numeric_field_value(rule.field, invoice=invoice, parsed=parsed)
    try:
        expected = Decimal(rule.value.strip())
    except (InvalidOperation, ValueError):
        return ValidationResult(
            rule_id,
            False,
            f"{rule.name}: invalid threshold '{rule.value}'",
            severity=rule.severity,
        )

    if actual is None:
        return ValidationResult(
            rule_id,
            False,
            f"{rule.name}: numeric field '{rule.field}' is missing",
            severity=rule.severity,
        )

    if op == "gte" and actual >= expected:
        return ValidationResult(rule_id, True, f"{rule.name}: {actual} >= {expected}", severity=rule.severity)
    if op == "lte" and actual <= expected:
        return ValidationResult(rule_id, True, f"{rule.name}: {actual} <= {expected}", severity=rule.severity)

    comparator = ">=" if op == "gte" else "<="
    return ValidationResult(
        rule_id,
        False,
        f"{rule.name}: {actual} must be {comparator} {expected}",
        severity=rule.severity,
    )


def run_custom_validation_rules(
    rules: list[CustomValidationRule],
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for rule in rules:
        if not rule.enabled:
            continue
        results.append(
            evaluate_custom_validation_rule(rule, invoice=invoice, parsed=parsed)
        )
    return results
