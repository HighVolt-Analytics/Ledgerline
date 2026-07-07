"""Run per-DT validation rules from the catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.custom_validation_rule import CustomValidationRule
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig
from app.services.rule_book.custom_validation_service import run_custom_validation_rules
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_validation_service import PROFILE_NON_ACTIONABLE
from app.services.rule_book.extended_validations import run_extended_validations
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.purchase.team_expense_validator import run_team_expense_validations
from app.services.rule_book.validation_rule_catalog import (
    PROFILE_DIRECT_EXPENSE_RULES,
    PROFILE_NON_ACTIONABLE_RULES,
    default_validation_rules_for_profile,
    has_explicit_finance_validation_rules,
    resolve_validation_rules,
)
from app.services.rule_book.validator import (
    ValidationResult,
    _skipped,
    vr01_total,
    vr03_compulsory_fields,
    vr03_direct_expense,
    vr03_grn_document,
    vr03_po_document,
    vr03_required,
    vr05_abn,
    vr07_currency,
    vr08_gst,
    vr02_unique,
)

PLAYBOOK_RULE_DEFAULT_SEVERITY: dict[str, str] = {
    "VR-PB01": "warn",
    "VR-PB02": "block",
    "VR-PB04": "warn",
}


def _definition_for_context(ctx: ValidationRunContext) -> DocumentTypeDefinition | None:
    code = (ctx.document_type_code or "").strip().upper()
    if not code:
        return None
    return get_document_type_definition(
        code,
        document_types=ctx.document_types,
        tenant_id=ctx.tenant_id,
    )


def _procurement_rules_for_definition(
    definition: DocumentTypeDefinition | None,
) -> list[ValidationRuleConfig]:
    """Match-mode checks (VR14–VR16) — configured via Processing playbook, not Validation."""
    if definition is None:
        return []
    from app.services.classification.document_type_playbook_profile_service import (
        effective_match_policy,
        match_mode_requires_po,
    )

    mode = effective_match_policy(definition).mode
    if mode == "none":
        return []

    rules: list[ValidationRuleConfig] = [
        ValidationRuleConfig(code="VR15", enabled=True, severity="block"),
    ]
    if match_mode_requires_po(mode) or mode in {"shipment", "receipt_line"}:
        rules.insert(
            0,
            ValidationRuleConfig(code="VR14", enabled=True, severity="block"),
        )
    if mode in {"three_way_po_grn", "shipment", "receipt_line"}:
        rules.append(ValidationRuleConfig(code="VR16", enabled=True, severity="warn"))
    return rules


def _runtime_validation_rules(
    finance_rules: list[ValidationRuleConfig],
    definition: DocumentTypeDefinition | None,
) -> list[ValidationRuleConfig]:
    """Finance rules from Validation tab; VR14–VR16 only when profile defaults apply."""
    if has_explicit_finance_validation_rules(definition):
        return list(finance_rules)
    merged = list(finance_rules)
    seen = {row.code for row in merged}
    for row in _procurement_rules_for_definition(definition):
        if row.code not in seen:
            merged.append(row)
            seen.add(row.code)
    return merged


@dataclass
class ValidationRunContext:
    data: object
    session: AsyncSession
    tenant_id: int
    exclude_id: int | None = None
    sender: str | None = None
    route_target: str | None = None
    purchase_document_type: str | None = None
    has_receipt_file: bool = False
    document_type_code: str | None = None
    validation_profile: str | None = None
    document_types: list | None = None
    playbook_gates: object | None = None
    invoice: Invoice | None = None


def _with_severity(result: ValidationResult, severity: str) -> ValidationResult:
    return ValidationResult(
        result.rule,
        result.passed,
        result.message,
        skipped=result.skipped,
        severity=severity,
    )


def _playbook_results_for_rules(
    playbook_gates: object | None,
    *,
    document_type_code: str | None = None,
    document_types: list | None = None,
    tenant_id: int | None = None,
) -> list[ValidationResult]:
    if playbook_gates is None:
        return []
    from app.services.classification.document_type_playbook_profile_service import should_enforce_bundle_mandatory
    from app.services.classification.document_type_playbook_service import playbook_validation_results

    definition = None
    code = (document_type_code or "").strip().upper()
    if code:
        definition = get_document_type_definition(
            code,
            document_types=document_types,
            tenant_id=tenant_id,
        )
    enforce_bundle = should_enforce_bundle_mandatory(definition) if definition else True

    rows: list[ValidationResult] = []
    for raw in playbook_validation_results(playbook_gates):
        if raw.rule == "VR-PB02" and not enforce_bundle:
            continue
        severity = PLAYBOOK_RULE_DEFAULT_SEVERITY.get(raw.rule, "warn")
        rows.append(
            ValidationResult(
                raw.rule,
                raw.passed,
                raw.message,
                severity=severity,
            )
        )
    return rows


async def _run_core_rule(code: str, ctx: ValidationRunContext) -> ValidationResult:
    data = ctx.data
    if code == "VR03":
        doc_type = ctx.purchase_document_type
        if doc_type == "po":
            return vr03_po_document(data)
        if doc_type == "grn":
            return vr03_grn_document(data)
        from app.services.classification.document_type_playbook_service import effective_required_fields
        from app.services.classification.document_type_validation_service import (
            PROFILE_DIRECT_EXPENSE,
            resolve_validation_profile,
        )

        definition = None
        dt_code = (ctx.document_type_code or "").strip().upper()
        if dt_code:
            definition = get_document_type_definition(
                dt_code,
                document_types=ctx.document_types,
                tenant_id=ctx.tenant_id,
            )
        compulsory = effective_required_fields(definition) if definition is not None else []
        if definition is not None and ctx.invoice is not None:
            return vr03_compulsory_fields(ctx.invoice, data, compulsory)

        profile = ctx.validation_profile or resolve_validation_profile(
            ctx.document_type_code,
            document_types=ctx.document_types,
            tenant_id=ctx.tenant_id,
        )
        if profile == PROFILE_DIRECT_EXPENSE:
            return vr03_direct_expense(data)
        return vr03_required(data)
    if code == "VR05":
        return await vr05_abn(
            data,
            ctx.session,
            tenant_id=ctx.tenant_id,
            sender=ctx.sender,
        )
    if code == "VR07":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_currency

        tenant = await ctx.session.get(Tenant, ctx.tenant_id)
        return vr07_currency(data, expected_currency=tenant_currency(tenant))
    if code == "VR08":
        from app.models.tenant import Tenant
        from app.tenant_settings import tenant_currency

        tenant = await ctx.session.get(Tenant, ctx.tenant_id)
        return vr08_gst(data, expected_currency=tenant_currency(tenant))
    if code == "VR01":
        return vr01_total(data)
    if code == "VR02":
        return await vr02_unique(
            data,
            ctx.session,
            ctx.exclude_id,
            tenant_id=ctx.tenant_id,
        )

    extended = await run_extended_validations(
        code,
        data,
        ctx.session,
        tenant_id=ctx.tenant_id,
        invoice=ctx.invoice,
        document_type_code=ctx.document_type_code,
        document_types=ctx.document_types,
    )
    if extended is not None:
        return extended
    return _skipped(code, f"Unknown validation rule {code}")


def _rules_for_context(ctx: ValidationRunContext) -> list[ValidationRuleConfig]:
    if ctx.purchase_document_type in {"po", "grn"}:
        resolved = resolve_validation_rules(
            ctx.document_type_code,
            document_types=ctx.document_types,
            tenant_id=ctx.tenant_id,
            validation_profile=ctx.validation_profile,
        )
        if resolved:
            return resolved
        return [
            ValidationRuleConfig(code="VR03", enabled=True, severity="block"),
            ValidationRuleConfig(code="VR07", enabled=True, severity="block"),
        ]

    profile = ctx.validation_profile
    if profile == PROFILE_NON_ACTIONABLE:
        return list(PROFILE_NON_ACTIONABLE_RULES)

    resolved = resolve_validation_rules(
        ctx.document_type_code,
        document_types=ctx.document_types,
        tenant_id=ctx.tenant_id,
        validation_profile=profile,
    )
    return resolved


def _custom_rules_for_context(ctx: ValidationRunContext) -> list[CustomValidationRule]:
    code = (ctx.document_type_code or "").strip().upper()
    if not code:
        return []
    definition = get_document_type_definition(
        code,
        document_types=ctx.document_types,
        tenant_id=ctx.tenant_id,
    )
    if definition is None:
        return []
    return list(definition.custom_validation_rules)


async def _run_universal_duplicate(ctx: ValidationRunContext) -> ValidationResult | None:
    from app.services.classification.document_type_validation_service import resolve_validation_profile
    from app.services.rule_book.validation_rule_catalog import enabled_rule_codes

    doc_type = (ctx.purchase_document_type or "").strip().lower()
    if doc_type in {"po", "grn"}:
        return None

    profile = ctx.validation_profile or resolve_validation_profile(
        ctx.document_type_code,
        document_types=ctx.document_types,
        tenant_id=ctx.tenant_id,
    )
    if profile == PROFILE_NON_ACTIONABLE:
        return None

    active_codes = enabled_rule_codes(_rules_for_context(ctx))
    if not active_codes:
        return None

    raw = await vr02_unique(
        ctx.data,
        ctx.session,
        ctx.exclude_id,
        tenant_id=ctx.tenant_id,
    )
    return _with_severity(raw, "block")


async def run_configured_validations(ctx: ValidationRunContext) -> list[ValidationResult]:
    if ctx.route_target == ROUTE_TEAM:
        team_results = await run_team_expense_validations(
            ctx.data,
            ctx.session,
            tenant_id=ctx.tenant_id,
            route_target=ctx.route_target,
            email_sender=ctx.sender,
            has_receipt_file=ctx.has_receipt_file,
        )
        rules = _rules_for_context(ctx)
        results: list[ValidationResult] = list(team_results)
        duplicate = await _run_universal_duplicate(ctx)
        if duplicate is not None:
            results.insert(0, duplicate)
        results.extend(
            _playbook_results_for_rules(
                ctx.playbook_gates,
                document_type_code=ctx.document_type_code,
                document_types=ctx.document_types,
                tenant_id=ctx.tenant_id,
            )
        )
        return results

    finance_rules = _rules_for_context(ctx)
    definition = _definition_for_context(ctx)
    rules = _runtime_validation_rules(finance_rules, definition)
    results: list[ValidationResult] = []

    duplicate = await _run_universal_duplicate(ctx)
    if duplicate is not None:
        results.append(duplicate)

    if rules:
        for row in rules:
            if not row.enabled or row.code.startswith("VR-PB"):
                continue
            raw = await _run_core_rule(row.code, ctx)
            results.append(_with_severity(raw, row.severity))

    results.extend(
        _playbook_results_for_rules(
            ctx.playbook_gates,
            document_type_code=ctx.document_type_code,
            document_types=ctx.document_types,
            tenant_id=ctx.tenant_id,
        )
    )

    if ctx.invoice is not None:
        custom_rules = _custom_rules_for_context(ctx)
        if custom_rules:
            results.extend(
                run_custom_validation_rules(
                    custom_rules,
                    invoice=ctx.invoice,
                    parsed=ctx.data,
                )
            )

    if ctx.route_target != ROUTE_TEAM and ctx.purchase_document_type not in ("po", "grn"):
        from app.services.classification.document_type_validation_service import (
            PROFILE_DIRECT_EXPENSE,
            PROFILE_NON_ACTIONABLE,
            resolve_validation_profile,
        )
        from app.services.rule_book.validation_rule_catalog import enabled_rule_codes

        profile = ctx.validation_profile or resolve_validation_profile(
            ctx.document_type_code,
            document_types=ctx.document_types,
            tenant_id=ctx.tenant_id,
        )
        active_codes = enabled_rule_codes(_rules_for_context(ctx))
        if (
            profile not in (PROFILE_NON_ACTIONABLE, PROFILE_DIRECT_EXPENSE)
            and active_codes
        ):
            team_extra = await run_team_expense_validations(
                ctx.data,
                ctx.session,
                tenant_id=ctx.tenant_id,
                route_target=ctx.route_target,
                email_sender=ctx.sender,
                has_receipt_file=ctx.has_receipt_file,
            )
            results.extend(team_extra)

    return results
