
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


def test_derive_matrix_flag_exception_awaiting_classification() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Anomaly Detected"
    assert reason is not None
    assert "document type" in reason.lower()
    assert "routed to" not in reason.lower()


def test_derive_matrix_flag_exception_pending_vendor() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_vendor",
        route_target="Purchase Management",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Anomaly Detected"
    assert reason is not None
    assert "vendor" in reason.lower()
    assert "routed to" not in reason.lower()


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


def test_exception_hold_reason_prefers_currency_over_suspense() -> None:
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.invoice.pipeline_stages import exception_hold_reason

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
        document_type_code="DT-11",
        route_target="Purchase Management",
        account_name="Suspense Account",
        account_code="9999",
        currency="",
        total=None,
    )
    dt = DocumentTypeDefinition(
        code="DT-11",
        title="Tax invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=["heading_invoice"],
        llmPrompt="",
        routeTarget="Purchase Management",
        enabled=True,
        requiredFields=["vendor", "total", "currency"],
        extractionFields=["vendor", "total", "currency"],
    )
    reason = exception_hold_reason(inv, document_types=[dt])
    assert "currency" in reason.lower() or "financial fields" in reason.lower()
    assert "suspense" not in reason.lower()


def test_exception_hold_reason_suspense_when_fields_complete() -> None:
    from app.services.invoice.pipeline_stages import exception_hold_reason

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
        document_type_code="DT-11",
        route_target="Purchase Management",
        account_name="Suspense Account",
        account_code="9999",
        currency="AUD",
        total=Decimal("250.00"),
    )
    reason = exception_hold_reason(inv)
    assert "suspense" in reason.lower() or "unmapped" in reason.lower()
    assert "lines" in reason.lower()


def test_derive_resolution_hint_fields_over_generic_drawer() -> None:
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
        document_type_code="DT-11",
        route_target="Purchase Management",
        account_name="Suspense Account",
        currency="",
        total=None,
    )
    hint = derive_resolution_hint(
        inv, [], configured_keys=["currency", "total", "vendor"]
    )
    assert hint is not None
    assert "fields" in hint.lower()
    assert "currency" in hint.lower() or "total" in hint.lower()
    assert "open document drawer" not in hint.lower()


def test_exception_hold_reason_auto_coded_is_posting_halt() -> None:
    from app.services.invoice.pipeline_stages import exception_hold_reason

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="auto_coded",
        document_type_code="DT-09",
        route_target="Team Expenses",
        account_code="EM-NEW-EMPLOYEE-FAD7",
        account_name="vishnu",
        currency="MMK",
        total=Decimal("2605000"),
    )
    reason = exception_hold_reason(inv)
    assert "posting halted" in reason.lower()
    assert "open document" not in reason.lower()


def test_derive_resolution_hint_journal_control_staff_advance() -> None:
    from datetime import datetime, timezone

    from app.models.audit import AuditLog
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="auto_coded",
        document_type_code="DT-09",
        route_target="Team Expenses",
        account_code="EM-NEW-EMPLOYEE-FAD7",
        account_name="vishnu",
        currency="MMK",
        total=Decimal("2605000"),
    )
    logs = [
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=748,
            event="journal_control_account_unresolved",
            detail={"unresolved": ["staff_advance_account"]},
            created_at=datetime.now(timezone.utc),
        )
    ]
    hint = derive_resolution_hint(inv, logs)
    assert hint is not None
    assert "chart of accounts" in hint.lower()
    assert "advance parent" in hint.lower()
    assert "staff advance" not in hint.lower()