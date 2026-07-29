
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Matrix flag and payment derivation."""

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.services.reports.matrix_service import derive_matrix_flag, derive_matrix_payment_status


def test_derive_matrix_flag_exception() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        validation_results='[{"rule":"VR01","passed":false,"message":"Total mismatch"}]',
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Anomaly Detected"
    assert reason == "Total mismatch"


def test_derive_matrix_flag_pending_approval() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Awaiting approval"
    assert reason is not None
    assert "approver" in reason.lower()


def test_derive_matrix_flag_awaiting_po_linkage() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Everest",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_po",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Awaiting linkage"
    assert reason == "Awaiting PO linkage"


def test_derive_matrix_payment_status_paid() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="Acme", status=InvoiceStatus.PROCESSED, total=Decimal("100"))
    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        amount=Decimal("100"),
        status=PaymentStatus.PAID,
    )
    assert derive_matrix_payment_status(inv, payment) == "Paid"


def test_derive_matrix_payment_status_on_hold() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
    )
    assert derive_matrix_payment_status(inv, None) == "On Hold"


def test_derive_matrix_flag_vault_needs_review_is_clean() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Archive Co",
        status=InvoiceStatus.PROCESSED,
        route_target="Vault",
        evaluation_status="needs_review",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Clean"
    assert reason is None
