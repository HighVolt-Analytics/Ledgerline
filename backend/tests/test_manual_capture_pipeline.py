"""Pipeline early branch for manual-entry skip extraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.invoice import InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.pipeline import _process_manual_entry_skip_extract
from app.services.rule_book.rule_book_mapper import ROUTE_EXPENSES


@pytest.mark.asyncio
async def test_manual_entry_skip_extract_continues_posting_when_header_ok() -> None:
    definition = DocumentTypeDefinition(
        code="DT-01",
        title="Tax invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        routeTarget=ROUTE_EXPENSES,
        playbookProfile="standard_transactional",
        requiredFields=["vendor", "total"],
        extractionFields=["vendor", "total"],
    )
    invoice = SimpleNamespace(
        id=99,
        document_ref="DOC-99",
        document_type_code="DT-01",
        document_type_confidence=1.0,
        route_target=ROUTE_EXPENSES,
        evaluation_status=None,
        status=InvoiceStatus.PARSING,
        vendor="Acme",
        total=10,
        extracted_fields={"manual_entry": "true", "vendor": "Acme", "total": "10"},
    )
    config = SimpleNamespace(document_types=[definition])
    org = SimpleNamespace()
    session = AsyncMock()

    with (
        patch(
            "app.services.invoice.pipeline._sync_counterparty_and_evaluate",
            new_callable=AsyncMock,
        ) as sync_eval,
        patch(
            "app.services.invoice.vision_posting_continue.continue_vision_understood_posting",
            new_callable=AsyncMock,
        ) as continue_posting,
        patch(
            "app.services.invoice.vision_posting_continue.vision_should_continue_posting",
            return_value=True,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.resolve_vision_posting_definition",
            return_value=definition,
        ),
        patch(
            "app.services.audit.audit_service.log_event",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.invoice_data.invoice_data_from_invoice",
            return_value=MagicMock(),
        ),
    ):
        await _process_manual_entry_skip_extract(
            session, invoice, config=config, org=org  # type: ignore[arg-type]
        )

    sync_eval.assert_awaited_once()
    continue_posting.assert_awaited_once()
    assert sync_eval.await_args.kwargs.get("force_dt_route") is True


@pytest.mark.asyncio
async def test_manual_entry_skip_extract_holds_review_when_not_continuing() -> None:
    definition = DocumentTypeDefinition(
        code="DT-01",
        title="Tax invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        routeTarget=ROUTE_EXPENSES,
        playbookProfile="standard_transactional",
    )
    invoice = SimpleNamespace(
        id=100,
        document_ref="DOC-100",
        document_type_code="DT-01",
        document_type_confidence=1.0,
        route_target=ROUTE_EXPENSES,
        evaluation_status=None,
        status=InvoiceStatus.PARSING,
        vendor=None,
        total=None,
        extracted_fields={"manual_entry": "true"},
    )
    config = SimpleNamespace(document_types=[definition])
    session = AsyncMock()

    with (
        patch(
            "app.services.invoice.pipeline._sync_counterparty_and_evaluate",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.vision_should_continue_posting",
            return_value=False,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.resolve_vision_posting_definition",
            return_value=definition,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.continue_vision_understood_posting",
            new_callable=AsyncMock,
        ) as continue_posting,
        patch(
            "app.services.audit.audit_service.log_event",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.invoice_data.invoice_data_from_invoice",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.shared.notifier.send_notification",
        ),
    ):
        await _process_manual_entry_skip_extract(
            session, invoice, config=config, org=SimpleNamespace()  # type: ignore[arg-type]
        )

    continue_posting.assert_not_awaited()
    assert invoice.status == InvoiceStatus.EXCEPTION
    assert invoice.evaluation_status == "needs_review"


@pytest.mark.asyncio
async def test_manual_entry_skip_extract_clears_duplicate_review_suggested() -> None:
    definition = DocumentTypeDefinition(
        code="DT-ADV",
        title="Advance",
        shortTitle="Advance",
        klass="Transactional",
        posting="Yes",
        routeTarget=ROUTE_EXPENSES,
        playbookProfile="employee_claim",
        requiredFields=["total"],
        extractionFields=["total"],
    )
    invoice = SimpleNamespace(
        id=42,
        document_ref="DOC-42",
        document_type_code="DT-ADV",
        document_type_confidence=1.0,
        route_target=ROUTE_EXPENSES,
        evaluation_status=None,
        status=InvoiceStatus.PARSING,
        vendor="Employee",
        total=50,
        duplicate_review_suggested=True,
        extracted_fields={"manual_entry": "true", "total": "50"},
    )
    config = SimpleNamespace(document_types=[definition])
    org = SimpleNamespace()
    session = AsyncMock()

    with (
        patch(
            "app.services.invoice.pipeline._sync_counterparty_and_evaluate",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.continue_vision_understood_posting",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.vision_should_continue_posting",
            return_value=False,
        ),
        patch(
            "app.services.invoice.vision_posting_continue.resolve_vision_posting_definition",
            return_value=definition,
        ),
        patch(
            "app.services.audit.audit_service.log_event",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.invoice_data.invoice_data_from_invoice",
            return_value=MagicMock(),
        ),
        patch("app.services.shared.notifier.send_notification"),
    ):
        await _process_manual_entry_skip_extract(
            session, invoice, config=config, org=org  # type: ignore[arg-type]
        )

    assert invoice.duplicate_review_suggested is False


@pytest.mark.asyncio
async def test_process_invoice_without_document_skips_no_stored_path() -> None:
    """Without-document rows have no file — must not fail parsing_failed/no_stored_path."""
    from app.services.invoice.pipeline import process_invoice

    invoice = SimpleNamespace(
        id=28776,
        tenant_id="tenant-1",
        document_ref="DOC-9",
        document_type_code="DT-05",
        status=InvoiceStatus.PENDING,
        raw_file_path=None,
        processing_overrides={"skip_extraction": True},
        extracted_fields={"without_document": "true", "manual_entry": "true"},
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace())
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    with (
        patch(
            "app.services.prompt_registry.warm_prompt_cache",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.pipeline.assign_document_ref",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.invoice.pipeline.human_approved_payable_bypass",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.services.invoice.invoice_edit_service.invoice_has_manual_field_edits",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.services.invoice.processing_override_catalog.consume_preserve_extracted_fields",
            return_value=False,
        ),
        patch(
            "app.services.invoice.processing_override_catalog.has_skip_extraction",
            return_value=True,
        ),
        patch(
            "app.services.invoice.pipeline.load_config_for_tenant",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(document_types=[]),
        ),
        patch(
            "app.services.invoice.pipeline.org_context_from_config",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.services.invoice.pipeline._process_manual_entry_skip_extract",
            new_callable=AsyncMock,
        ) as skip_extract,
        patch(
            "app.services.invoice.pipeline.log_event",
            new_callable=AsyncMock,
        ) as log_event,
    ):
        await process_invoice(session, invoice)  # type: ignore[arg-type]

    skip_extract.assert_awaited_once()
    assert all(
        (call.kwargs or {}).get("detail", {}).get("reason") != "no_stored_path"
        for call in log_event.await_args_list
    )
    assert invoice.status == InvoiceStatus.PARSING
