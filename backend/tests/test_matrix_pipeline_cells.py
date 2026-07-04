
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Matrix grid cells align with pipeline stage outcomes."""

from datetime import datetime, timezone

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.reports.matrix_service import derive_matrix_flag, derive_matrix_payment_status
from app.services.invoice.pipeline_stages import build_matrix_cells


def test_matrix_cells_duplicate_skipped_received_done_parsed_fail() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-1",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
    )
    dup_log = AuditLog(
        event="duplicate_skipped",
        invoice_id=1,
        detail={"original_invoice_id": 99, "filename": "invoice.pdf"},
        created_at=datetime.now(timezone.utc),
    )
    cells = build_matrix_cells(inv, [dup_log])
    by_stage = {cell["stage"]: cell for cell in cells}
    assert by_stage["Received"]["state"] == "done"
    assert by_stage["Parsed"]["state"] == "fail"
    assert "Duplicate" in by_stage["Parsed"]["detail"]
    assert by_stage["Validated"]["state"] == "pending"


def test_matrix_cells_rejected_parsed_fail() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.REJECTED,
        currency="AUD",
    )
    reject_log = AuditLog(
        event="invoice_rejected",
        invoice_id=1,
        detail={"actor_name": "Reviewer"},
        created_at=datetime.now(timezone.utc),
    )
    cells = build_matrix_cells(inv, [reject_log])
    by_stage = {cell["stage"]: cell for cell in cells}
    assert by_stage["Received"]["state"] == "done"
    assert by_stage["Parsed"]["state"] == "fail"
    assert by_stage["Mapped"]["state"] == "pending"


def test_matrix_cells_preserve_skipped_mapped_for_reference_document() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="SO-DEMO-100",
        status=InvoiceStatus.PROCESSED,
        route_target="Sales Management",
        sales_document_type="so",
        currency="AUD",
    )
    from datetime import datetime, timezone

    from app.models.audit import AuditLog

    complete_log = AuditLog(
        event="sales_document_processed",
        invoice_id=1,
        detail={},
        created_at=datetime.now(timezone.utc),
    )
    cells = build_matrix_cells(inv, [complete_log])
    by_stage = {cell["stage"]: cell for cell in cells}
    assert by_stage["Mapped"]["state"] == "skipped"
    assert "reference" in by_stage["Mapped"]["detail"].lower() or "not posted" in by_stage[
        "Mapped"
    ]["detail"].lower()


def test_derive_matrix_flag_awaiting_classification() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        evaluation_status="awaiting_classification",
    )
    flag, reason = derive_matrix_flag(inv)
    assert flag == "Anomaly Detected"
    assert reason is not None
    assert "classified" in reason.lower()


def test_derive_matrix_payment_on_hold_for_needs_rescan() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_rescan",
    )
    assert derive_matrix_payment_status(inv, None) == "On Hold"
