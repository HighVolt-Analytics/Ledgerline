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
