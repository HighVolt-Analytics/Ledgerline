"""Matrix flag and payment derivation."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.services.matrix_service import derive_matrix_flag, derive_matrix_payment_status


def test_derive_matrix_flag_exception() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        validation_results='[{"rule":"VR01","passed":false,"message":"Total mismatch"}]',
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Anomaly Detected"
    assert reason == "Total mismatch"


def test_derive_matrix_payment_status_paid() -> None:
    inv = Invoice(tenant_id=1, vendor="Acme", status=InvoiceStatus.PROCESSED, total=Decimal("100"))
    payment = Payment(
        tenant_id=1,
        invoice_id=1,
        amount=Decimal("100"),
        status=PaymentStatus.PAID,
    )
    assert derive_matrix_payment_status(inv, payment) == "Paid"


def test_derive_matrix_payment_status_on_hold() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
    )
    assert derive_matrix_payment_status(inv, None) == "On Hold"
