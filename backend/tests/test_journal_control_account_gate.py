"""Control/tax account COA resolution gate before journal persistence."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.classification.document_type_playbook_service import PlaybookGateResult
from app.services.invoice.file_validity_gate import FileValidityResult
from app.services.invoice.pipeline import process_invoice
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.rule_book.account_mapper import (
    AccountMapping,
    category_resolved_in_coa,
    resolve_category_for_config,
)
from app.services.rule_book.rule_book_mapper import ROUTE_SALES
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from tests.rule_book_test_helpers import demo_rule_book_config


def _trimmed_purchase_coa_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
            fallback_account="Suspense Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="6130", name="Marketing Expense", type="Expense"),
            # Fallback/suspense account itself must resolve too — only AP/tax are
            # deliberately missing in this fixture (see get_unresolved_control_accounts).
            ChartOfAccountEntry(code="9999", name="Suspense Account", type="Liability"),
        ],
    )


def _control_accounts_only_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            tax_account="GST Paid",
            payable_account="Accounts Payable",
            fallback_account="Suspense Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
            ChartOfAccountEntry(code="9999", name="Suspense Account", type="Liability"),
        ],
    )


def _trimmed_sales_coa_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="6130", name="Marketing Expense", type="Expense"),
            ChartOfAccountEntry(code="6140", name="R&D Expense", type="Revenue"),
            # PostingDefaults() default fallback_account is "Suspense Account" —
            # keep it resolvable so these tests isolate AR/tax, not the fallback gate.
            ChartOfAccountEntry(code="9999", name="Suspense Account", type="Liability"),
        ],
    )


def test_category_resolved_in_coa_matches_case_insensitive() -> None:
    config = demo_rule_book_config()
    assert category_resolved_in_coa("GST Paid", config) is True
    assert category_resolved_in_coa("gst paid", config) is True
    assert category_resolved_in_coa("Accounts Payable", config) is True
    assert category_resolved_in_coa("Missing Ledger", config) is False
    assert category_resolved_in_coa("", config) is False


def test_get_unresolved_control_accounts_purchase_missing_ap_and_tax() -> None:
    config = _trimmed_purchase_coa_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target="Purchase Management",
        currency="AUD",
    )
    assert get_unresolved_control_accounts(invoice=inv, config=config) == [
        "payable_account",
        "tax_account",
    ]


def test_get_unresolved_control_accounts_sales_missing_ar_and_tax() -> None:
    config = _trimmed_sales_coa_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_SALES,
        currency="AUD",
    )
    assert get_unresolved_control_accounts(invoice=inv, config=config) == [
        "receivable_account",
        "tax_account",
    ]


def test_get_unresolved_control_accounts_demo_coA_complete() -> None:
    config = demo_rule_book_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target="Purchase Management",
        currency="AUD",
    )
    assert get_unresolved_control_accounts(invoice=inv, config=config) == []


def test_general_category_suspense_still_allowed_when_control_accounts_present() -> None:
    config = _control_accounts_only_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 6, 14),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        route_target="Purchase Management",
        currency="AUD",
    )
    mapping = resolve_category_for_config("Unknown Expense Category", config)
    assert mapping.account_code == "9999"
    assert get_unresolved_control_accounts(invoice=inv, config=config) == []

    lines = generate_entries(inv, mapping, config=config)
    assert is_balanced(lines)
    expense_lines = [line for line in lines if line.account_code == "9999"]
    assert len(expense_lines) == 1
    payable_lines = [line for line in lines if line.account_code == "2000"]
    assert len(payable_lines) == 1


def test_sales_missing_control_accounts_still_produces_balanced_lines() -> None:
    """Balanced journals can still be wrong — gate must block before persist."""
    config = _trimmed_sales_coa_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("56495"),
        gst=Decimal("5084.55"),
        total=Decimal("61579.55"),
        route_target=ROUTE_SALES,
        currency="AUD",
    )
    mapping = AccountMapping("6130", "Marketing Expense")
    lines = generate_entries(inv, mapping, config=config)
    assert is_balanced(lines)
    assert get_unresolved_control_accounts(invoice=inv, config=config) == [
        "receivable_account",
        "tax_account",
    ]
    receivable_lines = [line for line in lines if line.debit > 0]
    tax_lines = [line for line in lines if line.credit > 0 and line.account_name == "Tax Collected"]
    assert receivable_lines[0].account_code == "9999"
    assert tax_lines[0].account_code == "9999"


@pytest.mark.asyncio
async def test_pipeline_blocks_unresolved_control_accounts(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _trimmed_purchase_coa_config()
    pdf_path = tmp_path / "control-gate.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="control-gate-hash",
        currency="AUD",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        invoice_date=date(2026, 6, 14),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        route_target="Purchase Management",
        processing_overrides={
            "skip_steps": [
                "image_quality",
                "classification",
                "validation",
                "line_gl_mapping",
            ]
        },
    )
    db_session.add(inv)
    await db_session.flush()

    ocr_text = (
        "TAX INVOICE from Acme with enough readable OCR text for quality gate to pass easily"
    )
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text=ocr_text,
        text_length=len(ocr_text),
        di_model="prebuilt-read",
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-01",
            confidence=0.9,
            reasoning="test",
            perspective="purchase",
        )

    async def _load_config(_session, _tenant_id):
        return config

    def _valid_file(*_args, **_kwargs):
        return FileValidityResult(passed=True, rejection_code=None, detail="ok")

    from tests.pipeline_test_helpers import patch_pre_ocr_gates_pass

    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr("app.services.invoice.file_validity_gate.evaluate_file_validity", _valid_file)
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.read_for_classification", _fake_read)
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", AsyncMock())
    monkeypatch.setattr("app.services.pipeline.apply_invoice_evaluation", AsyncMock())
    monkeypatch.setattr(
        "app.services.pipeline.evaluate_playbook_gates",
        AsyncMock(
            return_value=PlaybookGateResult(
                missing_bundle_mandatory=(),
                missing_bundle_conditional_dt=(),
                conditional_advisories=(),
                missing_extraction_fields=(),
            )
        ),
    )
    monkeypatch.setattr("app.services.invoice.pipeline.load_config_for_tenant", _load_config)
    monkeypatch.setattr("app.services.pipeline.load_config_for_tenant", _load_config)
    monkeypatch.setattr(
        "app.services.invoice.pipeline._resolve_header_mapping",
        lambda *_a, **_k: (
            AccountMapping("6130", "Marketing Expense"),
            type("D", (), {"rule_type": "document_type", "match_reason": "test"})(),
        ),
    )
    monkeypatch.setattr("app.services.pipeline.requires_gl_mapping_review", lambda *_a, **_k: False)
    monkeypatch.setattr("app.services.pipeline.apply_document_type_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.apply_vendor_hold_if_needed", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline._vendor_hold_unless_skipped", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.apply_team_expense_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.reconcile_daily", AsyncMock(return_value=type("R", (), {"halted": False})()))
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr(
        "app.services.integration.publish_service.publish_invoice_to_ledger",
        AsyncMock(),
    )
    monkeypatch.setattr("app.services.pipeline.send_notification", lambda *_a, **_k: None)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.status == InvoiceStatus.EXCEPTION
    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    control_events = [
        detail
        for event, detail in events
        if event == "journal_control_account_unresolved" and isinstance(detail, dict)
    ]
    assert len(control_events) == 1
    assert set(control_events[0].get("unresolved") or []) == {
        "payable_account",
        "tax_account",
    }
    journal_count = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()
    assert journal_count == 0
    assert not any(event == "journal_unbalanced" for event, _ in events)


@pytest.mark.asyncio
async def test_remap_skips_regen_when_control_accounts_unresolved(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _trimmed_purchase_coa_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="CTRL-REM-1",
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="control-remap",
        account_code="6130",
        account_name="Marketing Expense",
        route_target="Purchase Management",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6130", "Marketing Expense", Decimal("100"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("10"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("110"), EntryType.CREDIT),
    ]:
        db_session.add(
            JournalEntry(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                date=inv.invoice_date,
                account_code=code,
                account_name=name,
                debit=dr,
                credit=cr,
                entry_type=et,
            )
        )
    await db_session.flush()

    async def _load_config(_session, _tenant_id):
        return config

    monkeypatch.setattr("app.services.invoice.remap_service.load_config_for_tenant", _load_config)
    monkeypatch.setattr(
        "app.services.invoice.remap_service.reclassify_invoice_document_type",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr("app.services.invoice.remap_service.apply_invoice_evaluation", AsyncMock())
    monkeypatch.setattr("app.services.invoice.remap_service.sync_invoice_blob_path", lambda *_a, **_k: None)

    result = await remap_invoices_for_tenant(db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.journals_regenerated == 0
    assert inv.status == InvoiceStatus.PROCESSED

    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    control_events = [
        detail
        for event, detail in events
        if event == "journal_control_account_unresolved" and isinstance(detail, dict)
    ]
    assert len(control_events) == 1
    assert control_events[0].get("context") == "remap_skip"
    assert set(control_events[0].get("unresolved") or []) == {
        "payable_account",
        "tax_account",
    }

    entries = (
        await db_session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all()
    assert len(entries) == 3
    assert entries[0].account_code == "6130"
