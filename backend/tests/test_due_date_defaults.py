"""Tests for due-on-receipt due_date defaulting."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.due_date_defaults import (
    apply_due_on_receipt_to_invoice,
    apply_due_on_receipt_to_parsed,
    resolve_due_on_receipt_date,
)
from app.services.invoice.invoice_data import InvoiceData
from app.tenant_ids import TESTING_TENANT_UUID


def _posting_dt(*, required: list[str] | None = None) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-01",
        title="Tax Invoice",
        shortTitle="Tax Invoice",
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=["heading_invoice"],
        llmPrompt="",
        routeTarget="Purchase Management",
        enabled=True,
        requiredFields=required or ["vendor", "total"],
    )


def test_resolve_due_on_receipt_only_when_dt_requires() -> None:
    assert (
        resolve_due_on_receipt_date(
            due_date=None,
            invoice_date=date(2025, 7, 25),
            definition=None,
        )
        is None
    )
    defn = _posting_dt(required=["vendor", "total", "due_date"])
    assert resolve_due_on_receipt_date(
        due_date=None,
        invoice_date=date(2025, 7, 25),
        definition=defn,
    ) == date(2025, 7, 25)


def test_resolve_keeps_explicit_due_date() -> None:
    assert resolve_due_on_receipt_date(
        due_date=date(2025, 8, 1),
        invoice_date=date(2025, 7, 25),
    ) == date(2025, 8, 1)


def test_apply_to_invoice_sets_due_date_only_when_required() -> None:
    defn = _posting_dt(required=["vendor", "total", "due_date"])
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        vendor="Zuvan",
        total=Decimal("70000"),
        invoice_date=date(2025, 7, 25),
        due_date=None,
        file_hash="due-1",
    )
    assert apply_due_on_receipt_to_invoice(inv, defn) is True
    assert inv.due_date == date(2025, 7, 25)


def test_apply_to_parsed() -> None:
    defn = _posting_dt(required=["due_date"])
    parsed = InvoiceData(invoice_date=date(2025, 7, 25), total=Decimal("1"))
    assert apply_due_on_receipt_to_parsed(parsed, defn) is True
    assert parsed.due_date == date(2025, 7, 25)


def test_non_posting_dt_skips_default() -> None:
    vault = DocumentTypeDefinition(
        code="DT-06",
        title="Air Waybill",
        shortTitle="AWB",
        klass="Non-transactional",
        posting="No",
        recognitionMode="signals",
        recognitionSignals=["heading"],
        llmPrompt="",
        routeTarget="Vault",
        enabled=True,
        requiredFields=["due_date"],
    )
    assert (
        resolve_due_on_receipt_date(
            due_date=None,
            invoice_date=date(2025, 7, 25),
            definition=vault,
        )
        is None
    )


def test_vision_header_ok_without_due_date() -> None:
    from app.services.invoice.vision_posting_continue import vision_header_ok_from_invoice

    defn = _posting_dt(required=["vendor", "total"])
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-01",
        vendor="Zuvan",
        total=Decimal("70000"),
        invoice_date=date(2025, 7, 25),
        due_date=None,
        file_hash="due-2",
    )
    assert vision_header_ok_from_invoice(inv, defn) is True
    assert inv.due_date is None
