
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Matrix flag and payment derivation."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.services.reports.matrix_service import (
    derive_matrix_acc_sync,
    derive_matrix_advance_auth,
    derive_matrix_budget_auth,
    derive_matrix_flag,
    derive_matrix_payment_status,
    AUTH_DONE,
    AUTH_FAILED,
    AUTH_NA,
    AUTH_PENDING,
    SYNC_FAILED,
    SYNC_NA,
    SYNC_PENDING,
    SYNC_SYNCED,
)


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


@pytest.mark.asyncio
async def test_derive_matrix_flag_skips_deferred_ocr_blobs(
    db_session: AsyncSession,
) -> None:
    """Matrix list defers document_text/extracted_fields — must not MissingGreenlet."""
    from sqlalchemy import select

    from app.services.invoice.invoice_response_service import invoice_list_load_options

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Deferred Matrix",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-11",
        currency="AUD",
        total=Decimal("50.00"),
        document_text="large ocr body that must stay deferred " * 200,
        extracted_fields={"vision_header_confidence": "0.9"},
        file_hash="matrix-defer-greenlet",
        capture_source="upload",
    )
    db_session.add(inv)
    await db_session.flush()
    invoice_id = inv.id
    db_session.expire_all()

    deferred = (
        await db_session.execute(
            select(Invoice)
            .options(*invoice_list_load_options())
            .where(Invoice.id == invoice_id)
        )
    ).scalar_one()
    flag, reason = derive_matrix_flag(deferred)
    assert flag == "Anomaly Detected"
    assert reason is not None

    from app.services.invoice.invoice_response_service import invoice_to_response
    from app.services.invoice.pipeline_stages import derive_resolution_hint
    from app.services.invoice.vision_posting_continue import (
        EXTRACTED_AMOUNT_UNGROUNDED,
        extracted_bool_flag,
    )

    assert extracted_bool_flag(deferred, EXTRACTED_AMOUNT_UNGROUNDED) is False
    hint = derive_resolution_hint(deferred, [])
    assert hint is not None
    assert "complete header fields" in hint.lower()
    response = invoice_to_response(deferred, for_list=True, has_stored_file=False)
    assert response.resolution_hint == hint


def _te_dt(*, budget_control: bool = True, advance_control: bool = True):
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM

    return DocumentTypeDefinition(
        code="DT-TE",
        title="Employee claim",
        shortTitle="Claim",
        klass="Transactional",
        posting="Yes",
        routeTarget=ROUTE_TEAM,
        playbookProfile="employee_claim",
        budgetControl=budget_control,
        advanceControl=advance_control,
        postTo={"ledger": "Travel Expense"},
    )


def test_derive_matrix_advance_auth_na_outside_team_expenses() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase Management",
        document_type_code="DT-TE",
    )
    assert derive_matrix_advance_auth(inv, document_types=[_te_dt()]) == AUTH_NA


def test_derive_matrix_advance_auth_pending_and_done() -> None:
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM

    dts = [_te_dt(advance_control=True)]
    pending = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        team_expense_kind="expense_claim",
    )
    assert derive_matrix_advance_auth(pending, document_types=dts) == AUTH_PENDING

    done = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="auto_coded",
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        team_expense_kind="expense_claim",
    )
    assert derive_matrix_advance_auth(done, document_types=dts) == AUTH_DONE


def test_derive_matrix_advance_auth_off_unless_advance_kind() -> None:
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM

    dts = [_te_dt(advance_control=False)]
    claim = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        team_expense_kind="expense_claim",
    )
    assert derive_matrix_advance_auth(claim, document_types=dts) == AUTH_NA

    advance = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        team_expense_kind="advance_requisition",
    )
    assert derive_matrix_advance_auth(advance, document_types=dts) == AUTH_PENDING


def test_derive_matrix_budget_auth_from_vr_te08() -> None:
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM

    dts = [_te_dt(budget_control=True)]
    passed = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        validation_results='[{"rule":"VR-TE08","passed":true,"skipped":false,"message":"ok"}]',
    )
    assert derive_matrix_budget_auth(passed, document_types=dts) == AUTH_DONE

    soft = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        validation_results=(
            '[{"rule":"VR-TE08","passed":false,"skipped":false,'
            '"severity":"warn","message":"over"}]'
        ),
    )
    assert derive_matrix_budget_auth(soft, document_types=dts) == AUTH_PENDING

    hard = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        validation_results=(
            '[{"rule":"VR-TE08","passed":false,"skipped":false,'
            '"severity":"block","message":"over"}]'
        ),
    )
    assert derive_matrix_budget_auth(hard, document_types=dts) == AUTH_FAILED

    off = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Priya",
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_TEAM,
        document_type_code="DT-TE",
        validation_results='[{"rule":"VR-TE08","passed":false,"skipped":false}]',
    )
    assert (
        derive_matrix_budget_auth(off, document_types=[_te_dt(budget_control=False)])
        == AUTH_NA
    )


def test_derive_matrix_acc_sync_status() -> None:
    from app.models.accounting_export_ledger import STATUS_FAILED_TERMINAL, STATUS_SUCCESS
    from app.services.invoice.invoice_evaluation_service import ROUTE_VAULT

    posting = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase Management",
        purchase_document_type="invoice",
    )
    assert (
        derive_matrix_acc_sync(posting, ledger_status=STATUS_SUCCESS, ref_status=None)
        == SYNC_SYNCED
    )
    assert (
        derive_matrix_acc_sync(
            posting, ledger_status=STATUS_FAILED_TERMINAL, ref_status=None
        )
        == SYNC_FAILED
    )
    assert (
        derive_matrix_acc_sync(posting, ledger_status=None, ref_status=None)
        == SYNC_PENDING
    )

    vaulted = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_VAULT,
    )
    assert (
        derive_matrix_acc_sync(vaulted, ledger_status=STATUS_SUCCESS, ref_status=None)
        == SYNC_NA
    )


def test_derive_resolution_hint_ungrounded_amount_before_generic_header() -> None:
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
        extracted_fields={"amount_ungrounded": True},
        total=None,
    )
    hint = derive_resolution_hint(inv, [])
    assert hint is not None
    assert "could not be verified against document text" in hint.lower()
    assert "complete header fields" not in hint.lower()


def test_derive_resolution_hint_skips_ungrounded_when_total_present() -> None:
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
        extracted_fields={"amount_ungrounded": True},
        total=Decimal("100000"),
    )
    hint = derive_resolution_hint(inv, [])
    assert hint is not None
    assert "could not be verified against document text" not in hint.lower()


def test_derive_resolution_hint_amount_inconsistency_before_generic_header() -> None:
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
        extracted_fields={"amount_inconsistency": True},
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("999"),
    )
    hint = derive_resolution_hint(inv, [])
    assert hint is not None
    assert "do not add up" in hint.lower()
    assert "complete header fields" not in hint.lower()


def test_derive_resolution_hint_generic_header_when_no_amount_flags() -> None:
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=None,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
    )
    hint = derive_resolution_hint(inv, [])
    assert hint is not None
    assert "complete header fields" in hint.lower()


@pytest.mark.asyncio
async def test_derive_resolution_hint_inconsistent_amounts_when_extracted_fields_deferred(
    db_session: AsyncSession,
) -> None:
    """Matrix list defers JSON flags; column math still names the amount hold."""
    from sqlalchemy import select

    from app.services.invoice.invoice_response_service import (
        invoice_list_load_options,
        invoice_to_response,
    )
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Deferred Amounts",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
        currency="AUD",
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("999.00"),
        extracted_fields={"amount_inconsistency": True},
        file_hash="matrix-defer-amount-math",
        capture_source="upload",
    )
    db_session.add(inv)
    await db_session.flush()
    invoice_id = inv.id
    db_session.expire_all()

    deferred = (
        await db_session.execute(
            select(Invoice)
            .options(*invoice_list_load_options())
            .where(Invoice.id == invoice_id)
        )
    ).scalar_one()
    hint = derive_resolution_hint(deferred, [])
    assert hint is not None
    assert "do not add up" in hint.lower()
    response = invoice_to_response(deferred, for_list=True, has_stored_file=False)
    assert "do not add up" in (response.resolution_hint or "").lower()


@pytest.mark.asyncio
async def test_deferred_ungrounded_amount_falls_back_to_generic_header_hint(
    db_session: AsyncSession,
) -> None:
    """GAP: ungrounded-amount lives in deferred JSON, not a loaded scalar.

    Inconsistency can be re-derived from subtotal/gst/total on the list row.
    Ungrounded cannot — the amounts may still be present. Until a boolean
    column is added, Processing cards cannot tell this hold apart from a
    weak-identity header hold. This test locks the current fallback so the
    gap stays visible; do not "fix" it by undeferring extracted_fields.
    """
    from sqlalchemy import select

    from app.services.invoice.invoice_response_service import (
        invoice_list_load_options,
        invoice_to_response,
    )
    from app.services.invoice.pipeline_stages import derive_resolution_hint

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Deferred Ungrounded",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
        currency="AUD",
        total=Decimal("50.00"),
        extracted_fields={"amount_ungrounded": True},
        file_hash="matrix-defer-ungrounded-gap",
        capture_source="upload",
    )
    db_session.add(inv)
    await db_session.flush()
    invoice_id = inv.id
    db_session.expire_all()

    deferred = (
        await db_session.execute(
            select(Invoice)
            .options(*invoice_list_load_options())
            .where(Invoice.id == invoice_id)
        )
    ).scalar_one()
    hint = derive_resolution_hint(deferred, [])
    assert hint is not None
    assert "complete header fields" in hint.lower()
    assert "could not be verified" not in hint.lower()
    response = invoice_to_response(deferred, for_list=True, has_stored_file=False)
    assert "complete header fields" in (response.resolution_hint or "").lower()