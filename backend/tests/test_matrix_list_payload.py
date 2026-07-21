"""Matrix list must stay light — no OCR body, capped audit history."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_response_service import invoice_to_response
from app.tenant_ids import TESTING_TENANT_UUID


def test_matrix_invoice_payload_omits_document_text_when_for_list() -> None:
    """Regression: matrix used detail-mode invoice_to_response and loaded OCR bodies."""
    inv = Invoice(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        vendor="Acme",
        currency="",
        document_text="x" * 50_000,
        email_subject="big subject",
        created_at=datetime.now(timezone.utc),
    )
    response = invoice_to_response(inv, for_list=True)
    assert response.document_text is None
    assert response.email_subject is None
    assert response.vendor == "Acme"
