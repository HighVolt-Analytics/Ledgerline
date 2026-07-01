
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for approvals kanban column bucketing."""

from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval_board_service import approval_board_column


def _inv(
    *,
    status: InvoiceStatus,
    evaluation_status: str | None = None,
    document_type_code: str | None = None,
) -> Invoice:
    return Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=status,
        evaluation_status=evaluation_status,
        document_type_code=document_type_code,
        currency="AUD",
    )


def test_pre_classification_exception_review() -> None:
    assert (
        approval_board_column(
            _inv(
                status=InvoiceStatus.EXCEPTION,
                evaluation_status="awaiting_classification",
            )
        )
        == "review"
    )
    assert (
        approval_board_column(
            _inv(status=InvoiceStatus.EXCEPTION, evaluation_status="needs_rescan")
        )
        == "review"
    )
    assert (
        approval_board_column(_inv(status=InvoiceStatus.EXCEPTION, evaluation_status=None))
        == "review"
    )


def test_post_classification_exception_processing() -> None:
    for eval_status in ("needs_review", "awaiting_po", "pending_vendor"):
        assert (
            approval_board_column(
                _inv(
                    status=InvoiceStatus.EXCEPTION,
                    evaluation_status=eval_status,
                    document_type_code="DT-03",
                )
            )
            == "processing"
        )


def test_pipeline_processing() -> None:
    assert (
        approval_board_column(
            _inv(status=InvoiceStatus.PARSING, document_type_code="DT-03")
        )
        == "processing"
    )


def test_processed_approved() -> None:
    assert (
        approval_board_column(
            _inv(
                status=InvoiceStatus.PROCESSED,
                evaluation_status="auto_coded",
                document_type_code="DT-03",
            )
        )
        == "approved"
    )


def test_rejected_column() -> None:
    assert approval_board_column(_inv(status=InvoiceStatus.REJECTED)) == "rejected"
    assert (
        approval_board_column(_inv(status=InvoiceStatus.DUPLICATE_SKIPPED)) == "rejected"
    )
