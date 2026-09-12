"""Manual capture: field validation, skip-extraction flag, DT stamp helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.manual_capture_service import (
    ManualCaptureError,
    apply_manual_fields_to_invoice,
    parse_manual_fields_json,
    required_keys_for_manual_form,
    resolve_active_document_type,
    stamp_manual_capture_document_type,
    validate_manual_fields,
)
from app.services.invoice.processing_override_catalog import (
    has_skip_extraction,
    set_skip_extraction,
)
from app.services.rule_book.rule_book_mapper import ROUTE_TEAM


def _dt(
    code: str,
    *,
    title: str = "Claim",
    required: list[str] | None = None,
    extraction: list[str] | None = None,
    enabled: bool = True,
    route: str = ROUTE_TEAM,
    kind: str = "expense_claim",
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        short_title=title,
        klass="Transactional",
        posting="Yes",
        route_target=route,
        playbook_profile="employee_claim",
        team_expense_kind=kind,
        enabled=enabled,
        required_fields=required or [],
        extraction_fields=extraction or [],
    )


def test_parse_manual_fields_json_requires_object() -> None:
    with pytest.raises(ManualCaptureError):
        parse_manual_fields_json("")
    with pytest.raises(ManualCaptureError):
        parse_manual_fields_json("[]")
    assert parse_manual_fields_json('{"vendor":" Acme ","total":"12.5"}') == {
        "vendor": "Acme",
        "total": "12.5",
    }


def test_resolve_active_document_type_rejects_disabled() -> None:
    catalogue = [_dt("DT-04", enabled=False)]
    with pytest.raises(ManualCaptureError, match="disabled"):
        resolve_active_document_type("DT-04", catalogue)


def test_validate_manual_fields_requires_starred_keys() -> None:
    definition = _dt(
        "DT-04",
        required=["vendor", "total"],
        extraction=["vendor", "total", "invoice_date"],
    )
    with pytest.raises(ManualCaptureError, match="Missing required"):
        validate_manual_fields(definition, {"vendor": "Acme"})
    assert validate_manual_fields(
        definition, {"vendor": "Acme", "total": "10"}
    ) == ["vendor", "total"]


def test_validate_line_items_required_needs_rows() -> None:
    definition = _dt("DT-01", required=["line_items", "vendor"])
    with pytest.raises(ManualCaptureError, match="line_items"):
        validate_manual_fields(definition, {"vendor": "Acme"}, line_items=[])
    assert validate_manual_fields(
        definition,
        {"vendor": "Acme"},
        line_items=[{"description": "Widget", "amount": "10"}],
    ) == ["line_items", "vendor"]


def test_form_keys_union_required_and_extraction() -> None:
    from app.services.invoice.manual_capture_service import form_keys_for_manual_form

    definition = _dt(
        "DT-01",
        required=["vendor"],
        extraction=["vendor", "line_items", "total", "attachment_name"],
    )
    assert form_keys_for_manual_form(definition) == ["vendor", "line_items", "total"]


def test_required_keys_fallback_to_extraction_fields() -> None:
    definition = _dt(
        "DT-04",
        required=[],
        extraction=["vendor", "attachment_name", "total"],
    )
    assert required_keys_for_manual_form(definition) == ["vendor", "total"]


def test_stamp_sets_skip_extraction_and_dt() -> None:
    inv = SimpleNamespace(
        document_type_code=None,
        document_type_confidence=None,
        route_target=None,
        team_expense_kind=None,
        processing_overrides=None,
        extracted_fields=None,
    )
    definition = _dt("DT-09", title="Advance", kind="advance_requisition")
    stamp_manual_capture_document_type(inv, definition)  # type: ignore[arg-type]
    assert inv.document_type_code == "DT-09"
    assert inv.team_expense_kind == "advance_requisition"
    assert inv.route_target == ROUTE_TEAM
    assert has_skip_extraction(inv) is True  # type: ignore[arg-type]


def test_apply_manual_fields_writes_scalars_and_manual_flag() -> None:
    inv = SimpleNamespace(
        vendor=None,
        total=None,
        invoice_date=None,
        currency="",
        extracted_fields=None,
        account_code=None,
        account_name=None,
        so_reference=None,
        email_sender=None,
        abn=None,
        invoice_no=None,
        po_reference=None,
        cost_centre=None,
        billing_address=None,
        subtotal=None,
        gst=None,
        gst_rate=None,
        due_date=None,
        bank_bsb=None,
        bank_account=None,
        document_heading=None,
    )
    apply_manual_fields_to_invoice(
        inv,  # type: ignore[arg-type]
        {
            "vendor": "Cafe",
            "total": "42.50",
            "invoice_date": "2026-09-01",
            "employee_name": "Priya",
        },
    )
    assert inv.vendor == "Cafe"
    assert str(inv.total) == "42.50"
    assert inv.invoice_date is not None
    assert inv.extracted_fields["manual_entry"] == "true"
    assert inv.extracted_fields["employee_name"] == "Priya"


def test_has_skip_extraction_from_manual_entry_flag() -> None:
    inv = SimpleNamespace(
        processing_overrides=None,
        extracted_fields={"manual_entry": "true"},
    )
    assert has_skip_extraction(inv) is True  # type: ignore[arg-type]
    set_skip_extraction(inv)  # type: ignore[arg-type]
    assert inv.processing_overrides.get("skip_extraction") is True


@pytest.mark.asyncio
async def test_create_without_document_invoice_has_no_file() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.invoice.manual_capture_service import create_without_document_invoice

    definition = _dt("DT-ADV", kind="advance_requisition", required=["total"], extraction=["total"])
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    tenant_id = __import__("uuid").uuid4()

    created: list[object] = []

    def _add(obj: object) -> None:
        created.append(obj)
        setattr(obj, "id", 77)

    session.add.side_effect = _add

    with (
        patch(
            "app.services.credit_service.assert_can_upload",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.dossier.document_ref_service.allocate_next_document_ref",
            new_callable=AsyncMock,
            return_value="DOC-77",
        ),
        patch(
            "app.services.invoice.manual_capture_service.finalize_manual_capture_invoice",
            new_callable=AsyncMock,
        ) as finalize,
        patch(
            "app.services.audit.audit_service.log_event",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.credit_service.charge_upload_credits",
            new_callable=AsyncMock,
        ),
    ):
        inv = await create_without_document_invoice(
            session,
            tenant_id=tenant_id,
            definition=definition,
            fields={"total": "100"},
            actor_name="Priya",
            actor_email="priya@example.com",
            line_items=None,
        )

    assert inv.raw_file_path is None
    assert inv.file_hash is None
    assert inv.capture_source == "upload"
    assert inv.duplicate_review_suggested is False
    assert inv.document_ref == "DOC-77"
    finalize.assert_awaited_once()
    assert inv.extracted_fields.get("without_document") == "true"
    assert inv.extracted_fields.get("manual_entry") == "true"
    assert inv.processing_overrides is not None
    assert inv.processing_overrides.get("skip_extraction") is True
