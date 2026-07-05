"""Validation check catalogue and per-DT rule resolution."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig, normalize_validation_rules
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_validation_service import (
    PROFILE_DIRECT_EXPENSE,
    PROFILE_NON_ACTIONABLE,
    PROFILE_STANDARD,
    effective_validation_profile,
)

VALIDATION_CHECK_DESCRIPTIONS: dict[str, str] = {
    "VR02": "Exact, normalized, and fuzzy duplicate detection (always on for the organisation).",
    "VR03": "Compulsory fields for this document type must be present after OCR.",
    "VR05": "ABN / tax ID format and checksum validation.",
    "VR06": "Invoice date and due date must be valid.",
    "VR07": "Currency must match organisation country.",
    "VR08": "GST must match extracted tax rate × subtotal within tolerance.",
    "VR01": "Total must equal subtotal plus tax.",
    "VR09": "Line amounts must reconcile to subtotal; qty × price per line.",
    "VR10": "Tax Invoice wording required for taxable supplies ≥ AUD 1,000.",
    "VR11": "Invoice date cannot be future; over 12 months needs approval.",
    "VR12": "Vendor must exist in master; tax ID must match when present.",
    "VR14": "PO must be open and invoice currency must match PO.",
    "VR15": "PO, GRN, and invoice quantities and prices must match.",
    "VR16": "Freight and surcharges must be within tolerance against PO.",
    "VR-PB01": "Warns when optional (unstarred) extraction targets are missing. Compulsory gaps use VR03.",
    "VR-PB02": "Required supporting documents must exist on the same PO or SO reference.",
    "VR-PB04": "Recommended supporting documents (advisory only).",
}

VALIDATION_CHECK_LABELS: dict[str, str] = {
    "VR03": "Compulsory fields",
    "VR05": "ABN / tax ID",
    "VR06": "Invoice & due dates",
    "VR07": "Local currency",
    "VR08": "GST rate check",
    "VR01": "Total = subtotal + tax",
    "VR02": "Duplicate check (multi-layer)",
    "VR09": "Line arithmetic",
    "VR10": "Tax invoice (AU)",
    "VR11": "Date sanity",
    "VR12": "Vendor master",
    "VR14": "PO status & currency",
    "VR15": "Document match",
    "VR16": "Freight / surcharges",
    "VR-PB01": "Optional extraction fields",
    "VR-PB02": "Required supporting documents",
    "VR-PB04": "Recommended supporting documents",
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
    _rule("VR12", severity="block"),
]

PROFILE_PO_GOODS_RULES: list[ValidationRuleConfig] = list(PROFILE_STANDARD_RULES)

PROFILE_DIRECT_EXPENSE_RULES: list[ValidationRuleConfig] = [
    _rule("VR03"),
    _rule("VR09", severity="warn"),
    _rule("VR11", severity="warn"),
]

PROFILE_NON_ACTIONABLE_RULES: list[ValidationRuleConfig] = []

FINANCE_RULE_ORDER: tuple[str, ...] = (
    "VR03",
    "VR05",
    "VR06",
    "VR07",
    "VR08",
    "VR01",
    "VR09",
    "VR10",
    "VR11",
    "VR12",
)


def merge_configurable_validation_rules(
    explicit: Sequence[ValidationRuleConfig],
    *,
    validation_profile: str,
    document_type_code: str = "",
) -> list[ValidationRuleConfig]:
    """Fill missing finance rules — saved toggles win; gaps use profile defaults or disabled."""
    normalized = normalize_validation_rules(list(explicit))
    if not normalized:
        return []
    defaults = default_validation_rules_for_profile(
        validation_profile,
        document_type_code=document_type_code,
    )
    by_code = {row.code: row for row in normalized}
    default_by_code = {row.code: row for row in defaults}
    out: list[ValidationRuleConfig] = []
    for code in FINANCE_RULE_ORDER:
        if code in by_code:
            out.append(by_code[code])
        elif code in default_by_code:
            out.append(default_by_code[code])
        else:
            out.append(_rule(code, enabled=False))
    return out


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
    profile = effective_validation_profile(definition)
    if explicit:
        return merge_configurable_validation_rules(
            explicit,
            validation_profile=profile,
            document_type_code=definition.code,
        )
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
    profile = validation_profile or effective_validation_profile(definition)
    if explicit:
        return merge_configurable_validation_rules(
            explicit,
            validation_profile=profile,
            document_type_code=code,
        )

    return default_validation_rules_for_profile(profile, document_type_code=code)


def enabled_rule_codes(rules: Sequence[ValidationRuleConfig]) -> set[str]:
    return {row.code for row in rules if row.enabled}


def has_explicit_finance_validation_rules(definition: DocumentTypeDefinition | None) -> bool:
    """True when the Validation tab has saved per-rule toggles (not profile defaults only)."""
    if definition is None:
        return False
    return bool(normalize_validation_rules(definition.validation_rules))
