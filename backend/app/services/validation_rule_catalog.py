"""Validation check catalogue and per-DT rule resolution."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig, normalize_validation_rules
from app.services.document_type_catalog import get_document_type_definition
from app.services.document_type_validation_service import (
    PROFILE_DIRECT_EXPENSE,
    PROFILE_NON_ACTIONABLE,
    PROFILE_STANDARD,
    effective_validation_profile,
)

VALIDATION_CHECK_DESCRIPTIONS: dict[str, str] = {
    "VR02": "Exact, normalized, and fuzzy duplicate detection (always on for the organisation).",
    "VR03": "Required header fields and line items must be present after OCR.",
    "VR05": "ABN / tax ID format and checksum validation.",
    "VR06": "Invoice date and due date must be valid.",
    "VR07": "Currency must be AUD unless configured otherwise.",
    "VR08": "GST must be 10% of subtotal within tolerance.",
    "VR01": "Total must equal subtotal plus tax.",
    "VR09": "Line amounts must reconcile to subtotal; qty × price per line.",
    "VR10": "Tax Invoice wording required for taxable supplies ≥ AUD 1,000.",
    "VR11": "Invoice date cannot be future; over 12 months needs approval.",
    "VR12": "Vendor must exist in master; tax ID must match when present.",
    "VR14": "PO must be open and invoice currency must match PO.",
    "VR15": "PO, GRN, and invoice quantities and prices must match.",
    "VR16": "Freight and surcharges must be within tolerance against PO.",
    "VR-PB01": "Configured extraction fields should be captured on the invoice.",
    "VR-PB02": "Mandatory bundle document types must exist on the PO.",
    "VR-PB04": "Conditional bundle advisories for companion documents.",
}

VALIDATION_CHECK_LABELS: dict[str, str] = {
    "VR03": "Required fields & line items",
    "VR05": "ABN / tax ID",
    "VR06": "Invoice & due dates",
    "VR07": "Currency AUD",
    "VR08": "GST 10%",
    "VR01": "Total = subtotal + tax",
    "VR02": "Duplicate check (multi-layer)",
    "VR09": "Line arithmetic",
    "VR10": "Tax invoice (AU)",
    "VR11": "Date sanity",
    "VR12": "Vendor master",
    "VR14": "PO status & currency",
    "VR15": "Document match",
    "VR16": "Freight / surcharges",
    "VR-PB01": "Extraction completeness",
    "VR-PB02": "Mandatory bundle",
    "VR-PB04": "Conditional bundle advisories",
}

VALIDATION_CHECK_GROUPS: dict[str, str] = {
    "VR03": "Completeness",
    "VR05": "Tax",
    "VR06": "Dates",
    "VR07": "Currency",
    "VR08": "Tax",
    "VR01": "Arithmetic",
    "VR02": "Duplicate",
    "VR09": "Arithmetic",
    "VR10": "Tax",
    "VR11": "Dates",
    "VR12": "Vendor",
    "VR14": "Purchase order",
    "VR15": "Matching",
    "VR16": "Purchase order",
    "VR-PB01": "Playbook",
    "VR-PB02": "Playbook",
    "VR-PB04": "Playbook",
}


def _rule(code: str, *, severity: str = "block", enabled: bool = True) -> ValidationRuleConfig:
    return ValidationRuleConfig(code=code, enabled=enabled, severity=severity)  # type: ignore[arg-type]


PROFILE_STANDARD_RULES: list[ValidationRuleConfig] = [
    _rule("VR03"),
    _rule("VR05"),
    _rule("VR06"),
    _rule("VR07"),
    _rule("VR08"),
    _rule("VR01"),
    _rule("VR09"),
    _rule("VR10"),
    _rule("VR11"),
    _rule("VR12", severity="warn"),
    _rule("VR14", enabled=False),
    _rule("VR15", enabled=False),
    _rule("VR16", enabled=False),
    _rule("VR-PB01", severity="warn"),
    _rule("VR-PB02"),
    _rule("VR-PB04", severity="warn"),
]

PROFILE_PO_GOODS_RULES: list[ValidationRuleConfig] = [
    _rule("VR03"),
    _rule("VR05"),
    _rule("VR06"),
    _rule("VR07"),
    _rule("VR08"),
    _rule("VR01"),
    _rule("VR09"),
    _rule("VR10"),
    _rule("VR11"),
    _rule("VR12"),
    _rule("VR14"),
    _rule("VR15"),
    _rule("VR16", severity="warn"),
    _rule("VR-PB01", severity="warn"),
    _rule("VR-PB02"),
    _rule("VR-PB04", severity="warn"),
]

PROFILE_DIRECT_EXPENSE_RULES: list[ValidationRuleConfig] = [
    _rule("VR03"),
    _rule("VR09", severity="warn"),
    _rule("VR11", severity="warn"),
    _rule("VR-PB01", severity="warn"),
]

PROFILE_NON_ACTIONABLE_RULES: list[ValidationRuleConfig] = []


def default_validation_rules_for_profile(profile: str, *, document_type_code: str = "") -> list[ValidationRuleConfig]:
    _ = document_type_code
    token = (profile or "").strip().lower()
    if token == "po_goods":
        return list(PROFILE_PO_GOODS_RULES)
    if profile == PROFILE_NON_ACTIONABLE:
        return list(PROFILE_NON_ACTIONABLE_RULES)
    if profile == PROFILE_DIRECT_EXPENSE:
        return list(PROFILE_DIRECT_EXPENSE_RULES)
    return list(PROFILE_STANDARD_RULES)


def effective_validation_rules(definition: DocumentTypeDefinition) -> list[ValidationRuleConfig]:
    explicit = normalize_validation_rules(definition.validation_rules)
    if explicit:
        return explicit
    profile = effective_validation_profile(definition)
    return default_validation_rules_for_profile(profile, document_type_code=definition.code)


def resolve_validation_rules(
    document_type_code: str | None,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
    validation_profile: str | None = None,
) -> list[ValidationRuleConfig]:
    code = (document_type_code or "").strip().upper()
    if not code:
        profile = validation_profile or PROFILE_STANDARD
        return default_validation_rules_for_profile(profile)

    definition = get_document_type_definition(
        code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        profile = validation_profile or PROFILE_STANDARD
        return default_validation_rules_for_profile(profile, document_type_code=code)

    explicit = normalize_validation_rules(definition.validation_rules)
    if explicit:
        return explicit

    profile = validation_profile or effective_validation_profile(definition)
    return default_validation_rules_for_profile(profile, document_type_code=code)


def enabled_rule_codes(rules: Sequence[ValidationRuleConfig]) -> set[str]:
    return {row.code for row in rules if row.enabled}
