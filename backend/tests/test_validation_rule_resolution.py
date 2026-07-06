
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests that per-DT validation toggles are honoured at runtime."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig, normalize_validation_rules
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.rule_book.validation_rule_catalog import resolve_validation_rules
from app.services.classification.document_type_validation_service import (
    display_validation_pass_percent,
    validation_pass_applicable,
)
from app.services.rule_book.validation_runner import ValidationRunContext, run_configured_validations
from app.services.rule_book.validator import ValidationResult


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-16",
        title="Contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Vault",
        validationProfile="non_actionable",
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_resolve_validation_rules_honours_all_disabled() -> None:
    definition = _definition(
        validation_rules=[
            ValidationRuleConfig(code="VR03", enabled=False, severity="block"),
            ValidationRuleConfig(code="VR05", enabled=False, severity="block"),
        ]
    )
    rules = resolve_validation_rules(
        "DT-16",
        document_types=[definition],
    )
    assert len(rules) == 10
    assert all(not row.enabled for row in rules)


def test_resolve_validation_rules_uses_profile_when_unconfigured() -> None:
    definition = _definition(validation_rules=[], validationProfile="non_actionable")
    rules = resolve_validation_rules(
        "DT-16",
        document_types=[definition],
    )
    assert rules == []


def test_resolve_validation_rules_explicit_beats_forced_standard_profile() -> None:
    definition = _definition(
        validation_rules=[ValidationRuleConfig(code="VR03", enabled=False, severity="block")],
        validationProfile="standard",
    )
    rules = resolve_validation_rules(
        "DT-16",
        document_types=[definition],
        validation_profile="standard",
    )
    assert len(rules) == 10
    vr03 = next(row for row in rules if row.code == "VR03")
    assert vr03.enabled is False
    assert any(row.code == "VR05" and row.enabled for row in rules)


@pytest.mark.asyncio
async def test_run_configured_validations_skips_vr03_when_disabled() -> None:
    definition = _definition(
        validation_rules=[
            ValidationRuleConfig(code="VR03", enabled=False, severity="block"),
            ValidationRuleConfig(code="VR05", enabled=False, severity="block"),
            ValidationRuleConfig(code="VR01", enabled=False, severity="block"),
        ],
        validationProfile="non_actionable",
    )
    invoice = Invoice(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        document_type_code="DT-16",
    )
    data = InvoiceData(
        vendor=None,
        abn=None,
        invoice_no=None,
        line_items=[ParsedLineItem(description="Clause 1", qty=None, amount=None)],
    )
    ctx = ValidationRunContext(
        data=data,
        session=AsyncMock(),
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-16",
        document_types=[definition],
        invoice=invoice,
        playbook_gates=None,
    )
    ctx.session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )

    results = await run_configured_validations(ctx)
    assert not any(row.rule == "VR03" for row in results)
    assert not any("Missing:" in (row.message or "") for row in results)


def test_validation_pass_not_applicable_for_vault_non_actionable() -> None:
    definition = _definition(validationProfile="non_actionable")
    assert not validation_pass_applicable(
        route_target="Vault",
        document_type=definition,
    )
    rate = display_validation_pass_percent(
        [ValidationResult("VR03", False, "Missing compulsory: vendor")],
        applicable=False,
    )
    assert rate is None


def test_validation_pass_applicable_for_payable_invoice() -> None:
    definition = _definition(
        validationProfile="standard",
        posting="Yes",
        routeTarget="Purchase Management",
    )
    assert validation_pass_applicable(
        route_target="Purchase Management",
        document_type=definition,
    )
    rate = display_validation_pass_percent(
        [
            ValidationResult("VR01", True, "ok"),
            ValidationResult("VR03", False, "missing"),
        ],
        applicable=True,
    )
    assert rate == 50


def test_validation_rule_config_accepts_procurement_codes() -> None:
    row = ValidationRuleConfig(code="VR15", enabled=True, severity="block")
    assert row.code == "VR15"
    assert ValidationRuleConfig(code="VR14", enabled=True, severity="block").code == "VR14"


def test_normalize_validation_rules_keeps_finance_only() -> None:
    rules = normalize_validation_rules(
        [
            {"code": "VR03", "enabled": True, "severity": "block"},
            {"code": "VR15", "enabled": True, "severity": "block"},
            {"code": "VR-PB02", "enabled": True, "severity": "block"},
        ]
    )
    assert [row.code for row in rules] == ["VR03"]


def test_procurement_rules_build_without_schema_error() -> None:
    from app.services.rule_book.validation_runner import _procurement_rules_for_definition

    definition = _definition(
        code="DT-01",
        validationProfile="standard",
        posting="Yes",
        routeTarget="Purchase Management",
        playbookProfile="po_goods",
    )
    rules = _procurement_rules_for_definition(definition)
    assert any(row.code == "VR15" for row in rules)


@pytest.mark.asyncio
async def test_explicit_validation_rules_honour_user_toggles_only() -> None:
    """Validation tab toggles: enabled rules run; disabled + auto VR14/15 do not."""
    definition = _definition(
        code="DT-01",
        validationProfile="standard",
        posting="Yes",
        routeTarget="Purchase Management",
        playbookProfile="po_goods",
        validation_rules=[
            ValidationRuleConfig(code="VR03", enabled=True, severity="block"),
            ValidationRuleConfig(code="VR01", enabled=True, severity="block"),
            ValidationRuleConfig(code="VR12", enabled=True, severity="block"),
            ValidationRuleConfig(code="VR05", enabled=False, severity="block"),
            ValidationRuleConfig(code="VR07", enabled=False, severity="block"),
        ],
    )
    invoice = Invoice(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        document_type_code="DT-01",
        vendor="Unknown Supplier Ltd",
        invoice_no="INV-1",
        total=Decimal("100"),
        subtotal=Decimal("90.91"),
        gst=Decimal("9.09"),
        line_items=[],
    )
    data = InvoiceData(
        vendor="Unknown Supplier Ltd",
        invoice_no="INV-1",
        total=Decimal("100"),
        subtotal=Decimal("90.91"),
        gst=Decimal("9.09"),
        line_items=[ParsedLineItem(description="Item", qty=Decimal("1"), amount=Decimal("100"))],
        invoice_date=date.today(),
        due_date=date.today(),
    )
    ctx = ValidationRunContext(
        data=data,
        session=AsyncMock(),
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="DT-01",
        document_types=[definition],
        invoice=invoice,
        playbook_gates=None,
        route_target="Purchase Management",
    )
    ctx.session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )

    async def _mock_extended(code, *args, **kwargs):
        if code == "VR12":
            return ValidationResult("VR12", False, "Vendor not found in vendor master")
        return None

    with patch(
        "app.services.validation_runner.run_extended_validations",
        side_effect=_mock_extended,
    ):
        results = await run_configured_validations(ctx)
    codes = {row.rule for row in results}
    assert "VR05" not in codes
    assert "VR07" not in codes
    assert "VR14" not in codes
    assert "VR15" not in codes
    assert "VR03" in codes
    assert "VR12" in codes
    vr12 = next(row for row in results if row.rule == "VR12")
    assert vr12.passed is False
    assert vr12.severity == "block"
