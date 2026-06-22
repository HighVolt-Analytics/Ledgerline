"""Tests that per-DT validation toggles are honoured at runtime."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.validation_rule_catalog import resolve_validation_rules
from app.services.validation_runner import ValidationRunContext, run_configured_validations


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-16",
        title="Contract",
        shortTitle="Contract",
        klass="Supporting",
        posting="No",
        fraudRisk="low",
        oneLine="test",
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
    assert rules
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
    assert len(rules) == 1
    assert rules[0].code == "VR03"
    assert rules[0].enabled is False


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
        tenant_id=1,
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
        tenant_id=1,
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
