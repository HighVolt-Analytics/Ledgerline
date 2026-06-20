"""Tests for custom validation rules and universal duplicate check."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.custom_validation_rule import CustomValidationRule
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.validation_rule import ValidationRuleConfig
from app.services.custom_validation_service import evaluate_custom_validation_rule
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.validator import run_all_validations


def _invoice(**kwargs) -> Invoice:
    base = dict(
        id=1,
        org_id=1,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        vendor="Acme Pty Ltd",
    )
    base.update(kwargs)
    return Invoice(**base)


def test_custom_rule_field_present_passes() -> None:
    invoice = _invoice(vendor="Acme Pty Ltd")
    parsed = InvoiceData(vendor="Acme Pty Ltd")
    rule = CustomValidationRule(
        id="cv-1",
        name="Vendor required",
        field="vendor",
        operator="present",
    )
    result = evaluate_custom_validation_rule(rule, invoice=invoice, parsed=parsed)
    assert result.passed is True


def test_custom_rule_contains_fails() -> None:
    invoice = _invoice()
    parsed = InvoiceData(document_text="Standard invoice")
    rule = CustomValidationRule(
        id="cv-2",
        name="Warranty clause",
        field="document_text",
        operator="contains",
        value="warranty",
    )
    result = evaluate_custom_validation_rule(rule, invoice=invoice, parsed=parsed)
    assert result.passed is False


@pytest.mark.asyncio
async def test_universal_duplicate_always_runs(db_session: AsyncSession) -> None:
    data = InvoiceData(
        vendor="Acme Pty Ltd",
        abn="51824753556",
        invoice_no="INV-DUP-TEST",
        invoice_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        currency="AUD",
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        line_items=[ParsedLineItem(description="Item", amount=Decimal("100"))],
        document_text="Tax Invoice",
    )
    results = await run_all_validations(
        data,
        db_session,
        org_id=1,
        document_type_code="DT-03",
        document_types=[
            DocumentTypeDefinition.model_validate(
                {
                    "code": "DT-03",
                    "title": "Direct expense",
                    "shortTitle": "Direct",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "fraudRisk": "low",
                    "oneLine": "Test",
                    "validationProfile": "direct_expense",
                    "validationRules": [
                        ValidationRuleConfig(code="VR03", enabled=True, severity="block"),
                    ],
                }
            )
        ],
    )
    assert any(r.rule == "VR02" for r in results)
