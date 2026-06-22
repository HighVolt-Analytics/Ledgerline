"""Tests for per-DT validation profiles and reclassification."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.rule_book_config import DocumentClassificationConfig, validate_rule_book_config_payload
from app.services.document_type_classifier import classify_document_type
from app.services.document_type_reclassify_service import reclassify_invoice_document_type
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.validator import all_passed, run_all_validations


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=1, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _directus_parsed() -> InvoiceData:
    return InvoiceData(
        vendor="Directus Cloud",
        invoice_no="INV-9",
        invoice_date=date(2026, 3, 1),
        total=Decimal("99.00"),
        currency="USD",
        line_items=[ParsedLineItem(description="SaaS subscription", amount=Decimal("99"))],
    )


@pytest.mark.asyncio
async def test_dt21_direct_expense_omits_abn_and_gst(
    db_session: AsyncSession,
    capture_config,
) -> None:
    results = await run_all_validations(
        _directus_parsed(),
        db_session,
        tenant_id=1,
        document_type_code="DT-21",
        validation_profile="direct_expense",
        document_types=list(capture_config.document_types),
    )
    assert all_passed(results)
    assert not any(r.rule == "VR05" for r in results)
    assert not any(r.rule == "VR08" for r in results)


@pytest.mark.asyncio
async def test_reclassify_updates_document_type_from_fields(
    db_session: AsyncSession,
    capture_config,
) -> None:
    inv = Invoice(
        tenant_id=1,
        status=InvoiceStatus.EXCEPTION,
        currency="USD",
        vendor="Directus Cloud",
        invoice_no="INV-9",
        total=Decimal("99.00"),
        email_attachment_name="saas-invoice.pdf",
        document_type_code="DT-24",
        document_type_confidence=0.45,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="SaaS subscription",
            amount=Decimal("99.00"),
        )
    )
    await db_session.flush()
    inv = (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    changed = await reclassify_invoice_document_type(
        db_session,
        inv,
        config=capture_config,
        parse_confidence="high",
    )
    assert changed is True
    assert inv.document_type_code in {"DT-03", "DT-04", "DT-21"}
    assert float(inv.document_type_confidence or 0) >= 0.65


def test_catalogue_present_no_classifier_match_returns_unclassified(capture_config) -> None:
    invoice = Invoice(
        id=1,
        tenant_id=1,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        email_attachment_name="totally-unknown.pdf",
        vendor="Mystery Co",
    )
    parsed = InvoiceData(vendor="Mystery Co")
    result = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=capture_config.document_types,
        unclassified=DocumentClassificationConfig(unclassified_document_type_code="DT-24"),
        parse_confidence="high",
    )
    assert result.code == "DT-24"
    assert "No classifier matched" in result.reason


def test_dt16_matches_contract_body_without_filename(capture_config) -> None:
    body = (
        "AFMA Environmental Products Spot Contract signed for and on behalf of SELLER "
        "governing law and jurisdiction NSW"
    )
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="uuid-file.pdf"),
        parsed=InvoiceData(document_text=body),
        document_types=capture_config.document_types,
        parse_confidence="high",
    )
    assert result.code == "DT-16"
