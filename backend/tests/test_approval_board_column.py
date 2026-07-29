
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for approvals kanban column bucketing."""

from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval.approval_board_service import approval_board_column


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
    for eval_status in ("needs_review", "awaiting_po", "pending_vendor", "pending_approval"):
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


def test_pending_approval_without_classification_still_processing() -> None:
    assert (
        approval_board_column(
            _inv(
                status=InvoiceStatus.EXCEPTION,
                evaluation_status="pending_approval",
                document_type_code="DT-26",
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


def test_understood_path_vaulted_goes_to_approved() -> None:
    from app.services.approval.approval_board_service import (
        is_understood_path_complete,
        is_understood_path_not_approvable,
        is_understood_path_vault_terminal,
    )

    vaulted = _inv(status=InvoiceStatus.EXCEPTION, evaluation_status="vision_vaulted")
    assert approval_board_column(vaulted) == "approved"
    assert is_understood_path_complete(vaulted)
    assert is_understood_path_not_approvable(vaulted)
    assert is_understood_path_vault_terminal(vaulted)

    header = _inv(status=InvoiceStatus.EXCEPTION, evaluation_status="vision_header_review")
    assert approval_board_column(header) == "review"
    assert not is_understood_path_not_approvable(header)
    assert not is_understood_path_vault_terminal(header)

    header_with_dt = _inv(
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_header_review",
        document_type_code="DT-07",
    )
    assert approval_board_column(header_with_dt) == "processing"

    # Legacy understood rows still tagged awaiting_classification but soft-bundled.
    legacy = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        extracted_fields={"vision_bundle_kind": "soft", "vision_bundle_key": "INV-1"},
        currency="AUD",
    )
    assert approval_board_column(legacy) == "approved"
    assert is_understood_path_complete(legacy)

    # OCR classification hold still belongs in To review (and remains Confirmable).
    ocr = _inv(status=InvoiceStatus.EXCEPTION, evaluation_status="awaiting_classification")
    assert approval_board_column(ocr) == "review"
    assert not is_understood_path_not_approvable(ocr)
