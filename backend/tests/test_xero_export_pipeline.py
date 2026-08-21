"""Xero accounting export pipeline unit tests."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.accounting_entity_mapping import (
    MAPPING_GL_ACCOUNT,
    MAPPING_SUPPLIER,
    MAPPING_TAX,
    AccountingEntityMapping,
)
from app.models.accounting_export_ledger import (
    ATTACHMENT_SUCCESS,
    STATUS_FAILED_TERMINAL,
    STATUS_HUMAN_REVIEW,
    STATUS_RETRY_PENDING,
    STATUS_SUCCESS,
    AccountingExportLedger,
)
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_tax_rate import XeroTaxRate
from app.schemas.canonical_accounting_transaction import (
    CanonicalAccountingTransaction,
    CanonicalLine,
    CanonicalSupplier,
    compute_payload_hash,
    validate_canonical_totals,
)
from app.services.integration.accounting_mapping_service import get_mapping, upsert_mapping
from app.services.integration.canonical_transaction_builder import (
    build_canonical_supplier_invoice,
)
from app.services.integration.xero.xero_accpay_adapter import (
    assert_draft_status,
    build_accpay_draft_payload,
)
from app.services.integration.xero.xero_client import XeroApiError
from app.services.integration.xero.xero_contact_resolution_service import (
    resolve_supplier_contact,
)
from app.services.integration.xero.xero_error_classification import (
    ERROR_TERMINAL,
    ERROR_TRANSIENT,
    classify_error,
)
from app.services.integration.xero.xero_export_service import (
    export_supplier_invoice_to_xero,
    retry_attachment,
    validate_invoice_for_xero_export,
)
from app.tenant_ids import TESTING_TENANT_UUID


async def _seed_xero_ready(db_session):
    integration = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id="xero-org-1",
        access_token_encrypted="enc-access",
        refresh_token_encrypted="enc-refresh",
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(integration)
    await db_session.flush()

    db_session.add(
        XeroAccount(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            xero_account_id="acc-1",
            code="400",
            name="Purchases",
            status="ACTIVE",
            sync_status="active",
        )
    )
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            tax_type="INPUT",
            name="GST on Expenses",
            sync_status="active",
        )
    )
    db_session.add(
        XeroCurrency(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            code="AUD",
            sync_status="active",
        )
    )
    db_session.add(
        XeroContact(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            xero_contact_id="contact-1",
            name="Acme Supplies",
            email_address="ap@acme.test",
            tax_number="51824753556",
            is_supplier=True,
            sync_status="active",
        )
    )
    await db_session.flush()
    return integration


async def _seed_invoice(
    db_session, *, vendor="Acme Supplies", abn="51824753556", currency="AUD"
):
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=vendor,
        abn=abn,
        invoice_no="INV-100",
        document_ref="DOC-100",
        invoice_date=date(2026, 1, 15),
        due_date=date(2026, 2, 15),
        currency=currency,
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        gst_rate=Decimal("10"),
        total=Decimal("110.00"),
        status=InvoiceStatus.PROCESSED,
        account_code="400",
        raw_file_path="tenant/test/invoice.pdf",
        email_attachment_name="invoice.pdf",
        storage_vendor_slug="acme-supplies",
        email_sender="ap@acme.test",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal("2"),
            unit_price=Decimal("50.00"),
            amount=Decimal("100.00"),
            tax_amount=Decimal("10.00"),
        )
    )
    await db_session.flush()
    loaded = (
        await db_session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == inv.id)
        )
    ).scalar_one()
    return loaded


@pytest.mark.asyncio
async def test_canonical_transaction_validation(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    txn = build_canonical_supplier_invoice(
        inv, tenant_id=TESTING_TENANT_UUID, posting_currency="AUD"
    )
    assert txn.transaction_type == "SUPPLIER_INVOICE"
    assert txn.payload_hash
    assert txn.idempotency_key
    assert validate_canonical_totals(txn) == []
    # Totals mismatch
    bad = CanonicalAccountingTransaction(
        qll_transaction_id=str(uuid.uuid4()),
        tenant_id=str(TESTING_TENANT_UUID),
        source_invoice_id=1,
        currency="AUD",
        supplier=CanonicalSupplier(legal_name="X"),
        lines=[
            CanonicalLine(
                line_id="1",
                description="a",
                quantity=1,
                unit_price=Decimal("10"),
                line_amount=Decimal("10"),
            )
        ],
        subtotal=Decimal("10"),
        tax_total=Decimal("1"),
        total=Decimal("999"),
        idempotency_key="k",
        payload_hash="h",
    )
    errs = validate_canonical_totals(bad)
    assert any(e["code"] == "totals_do_not_reconcile" for e in errs)


@pytest.mark.asyncio
async def test_tenant_isolation_mappings(db_session):
    await _seed_xero_ready(db_session)
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_GL_ACCOUNT,
        source_key="400",
        external_code="400",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    other = uuid.uuid4()
    rows = (
        await db_session.execute(
            select(AccountingEntityMapping).where(
                AccountingEntityMapping.tenant_id == other
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_mapping_completeness_and_inactive(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    # Without mappings / tax mapping ΓÇö validation fails for tax
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "tax_type_not_mapped" in codes

    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    with pytest.raises(Exception):
        await upsert_mapping(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            mapping_type=MAPPING_GL_ACCOUNT,
            source_key="999",
            external_code="999",
            user_id=1,
            xero_tenant_id="xero-org-1",
        )


@pytest.mark.asyncio
async def test_contact_exact_match_and_ambiguous(db_session):
    integration = await _seed_xero_ready(db_session)
    db_session.add(
        XeroContact(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            xero_contact_id="contact-2",
            name="Acme Supplies",
            is_supplier=True,
            sync_status="active",
        )
    )
    await db_session.flush()

    match = await resolve_supplier_contact(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        supplier_key="acme",
        legal_name="Acme Supplies",
        tax_id="51824753556",
    )
    assert match.outcome == "matched"
    assert match.contact_id == "contact-1"
    assert match.reason == "tax_id"

    amb = await resolve_supplier_contact(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        xero_tenant_id="xero-org-1",
        supplier_key="acme",
        legal_name="Acme Supplies",
    )
    assert amb.outcome == "ambiguous"


@pytest.mark.asyncio
async def test_validation_allows_auto_create_when_no_supplier_match(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(
        db_session,
        vendor="Brand New Supplier Pty Ltd",
        abn="11111111111",
    )
    inv.storage_vendor_slug = "brand-new-supplier"
    inv.email_sender = "ap@brandnew.test"
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    await db_session.flush()
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "contact_not_mapped" not in codes
    assert "ambiguous_supplier_match" not in codes
    assert result["contact_resolution"]["outcome"] == "none"
    assert result["contact_resolution"]["contact_id"] is None
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_export_auto_creates_supplier_when_no_match(db_session, tmp_path):
    integration = await _seed_xero_ready(db_session)
    inv = await _seed_invoice(
        db_session,
        vendor="Brand New Supplier Pty Ltd",
        abn="11111111111",
    )
    inv.storage_vendor_slug = "brand-new-supplier"
    inv.email_sender = "ap@brandnew.test"
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    inv.raw_file_path = str(pdf)
    await db_session.flush()

    mock_client = MagicMock()

    async def _post_json(path, json_body=None, **kwargs):
        if path == "Contacts":
            return {
                "Contacts": [
                    {
                        "ContactID": "contact-new-1",
                        "Name": "Brand New Supplier Pty Ltd",
                        "EmailAddress": "ap@brandnew.test",
                        "TaxNumber": "11111111111",
                        "ContactStatus": "ACTIVE",
                    }
                ]
            }
        return {
            "Invoices": [
                {
                    "InvoiceID": "xero-inv-new",
                    "InvoiceNumber": "INV-100",
                    "Status": "DRAFT",
                    "CurrencyCode": "AUD",
                    "Total": "110.00",
                }
            ]
        }

    mock_client.post_json = AsyncMock(side_effect=_post_json)
    mock_client.put_bytes = AsyncMock(
        return_value=MagicMock(
            content=b'{"Attachments":[{"AttachmentID":"att-1"}]}',
            json=lambda: {"Attachments": [{"AttachmentID": "att-1"}]},
        )
    )

    with (
        patch(
            "app.services.integration.xero.xero_export_service.require_xero_ready",
            AsyncMock(return_value=(integration, "xero-org-1")),
        ),
        patch(
            "app.services.integration.xero.xero_contact_resolution_service.require_xero_ready",
            AsyncMock(return_value=(integration, "xero-org-1")),
        ),
        patch(
            "app.services.integration.xero.xero_export_service.XeroClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.integration.xero.xero_contact_resolution_service.XeroClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.integration.xero.xero_attachment_service.XeroClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.integration.xero.xero_attachment_service.open_pdf_for_reading",
        ) as open_pdf,
    ):
        open_pdf.return_value.__enter__ = lambda s: MagicMock(
            read=lambda: b"%PDF-1.4 test"
        )
        open_pdf.return_value.__exit__ = lambda *a: None
        result = await export_supplier_invoice_to_xero(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            user_id=1,
        )

    assert result["evidence"]["external_id"] == "xero-inv-new"
    mapping = await get_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_SUPPLIER,
        source_key="brand-new-supplier",
        xero_tenant_id="xero-org-1",
    )
    assert mapping is not None
    assert mapping.external_id == "contact-new-1"
    contact_calls = [
        c for c in mock_client.post_json.await_args_list if c.args and c.args[0] == "Contacts"
    ]
    assert len(contact_calls) == 1


def test_accpay_draft_enforced():
    txn = CanonicalAccountingTransaction(
        qll_transaction_id="qll-1",
        tenant_id=str(TESTING_TENANT_UUID),
        source_invoice_id=1,
        currency="AUD",
        supplier=CanonicalSupplier(legal_name="Acme"),
        lines=[
            CanonicalLine(
                line_id="1",
                description="Widgets",
                quantity=Decimal("1"),
                unit_price=Decimal("10"),
                line_amount=Decimal("10"),
                mapped_xero_account_code="400",
                mapped_xero_tax_type="INPUT",
            )
        ],
        subtotal=Decimal("10"),
        tax_total=Decimal("1"),
        total=Decimal("11"),
        idempotency_key="k",
        payload_hash="h",
        source_document_id="INV-1",
    )
    payload = build_accpay_draft_payload(txn, contact_id="contact-1")
    assert payload["Type"] == "ACCPAY"
    assert payload["Status"] == "DRAFT"
    assert payload["Reference"] == "QLL:qll-1"
    assert payload["Contact"]["ContactID"] == "contact-1"
    assert_draft_status(payload)
    payload["Status"] = "AUTHORISED"
    with pytest.raises(ValueError):
        assert_draft_status(payload)


def test_error_classification_transient_and_terminal():
    t = classify_error(exc=XeroApiError(status_code=429, error_code="rate", message="slow"))
    assert t.bucket == ERROR_TRANSIENT
    assert t.retryable is True
    term = classify_error(code="unsupported_currency", message="bad currency", status_code=400)
    assert term.bucket == ERROR_TERMINAL
    assert term.retryable is False
    assert classify_error(code="currency_not_supported", message="x").bucket == ERROR_TERMINAL
    assert classify_error(code="currency_missing", message="y").bucket == ERROR_TERMINAL


@pytest.mark.asyncio
async def test_export_currency_blank_source_is_currency_missing(db_session):
    """Blank invoice.currency must not fall back to organisation AUD."""
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session, currency="")
    assert inv.currency == ""
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_missing" in codes
    assert result["valid"] is False
    assert result["canonical"]["currency"] == ""


@pytest.mark.asyncio
async def test_export_currency_foreign_not_supported_when_not_synced(db_session):
    """Foreign document currency must not be silently replaced with AUD."""
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session, currency="USD")
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_not_supported" in codes
    assert "currency_missing" not in codes
    assert result["canonical"]["currency"] == "USD"
    assert inv.currency == "USD"


@pytest.mark.asyncio
async def test_export_currency_document_usd_when_synced(db_session):
    """Normalised document currency is used when active for the selected org."""
    await _seed_xero_ready(db_session)
    # Seed only has AUD; add USD for selected org.
    integration = (
        await db_session.execute(
            select(AccountingIntegration).where(
                AccountingIntegration.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()
    db_session.add(
        XeroCurrency(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            code="USD",
            sync_status="active",
        )
    )
    await db_session.flush()
    inv = await _seed_invoice(db_session, currency=" usd ")
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_missing" not in codes
    assert "currency_not_supported" not in codes
    assert result["canonical"]["currency"] == "USD"


@pytest.mark.asyncio
async def test_export_currency_success_ledger_immutable_on_retry(db_session):
    """Existing SUCCESS export currency stays fixed even if document currency changes."""
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session, currency="AUD")
    db_session.add(
        AccountingExportLedger(
            tenant_id=TESTING_TENANT_UUID,
            provider="xero",
            qll_transaction_id=str(uuid.uuid4()),
            source_invoice_id=inv.id,
            source_document_id=f"DOC-{inv.id}",
            transaction_type="SUPPLIER_INVOICE",
            direction="OUTBOUND",
            status=STATUS_SUCCESS,
            payload_version=1,
            payload_hash="hash-ccy",
            idempotency_key="idem-ccy",
            external_id="xero-inv-ccy",
            external_currency="AUD",
            external_status="DRAFT",
        )
    )
    inv.currency = "USD"
    await db_session.flush()
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    assert result["canonical"]["currency"] == "AUD"
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_not_supported" not in codes


@pytest.mark.asyncio
async def test_accpay_due_date_mapped_when_present(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    inv.due_date = date(2026, 2, 28)
    await db_session.flush()
    txn = build_canonical_supplier_invoice(
        inv, tenant_id=TESTING_TENANT_UUID, posting_currency="AUD"
    )
    payload = build_accpay_draft_payload(txn, contact_id="contact-1")
    assert payload["DueDate"] == "2026-02-28"


@pytest.mark.asyncio
async def test_accpay_due_date_absent_when_missing(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    inv.due_date = None
    await db_session.flush()
    txn = build_canonical_supplier_invoice(
        inv, tenant_id=TESTING_TENANT_UUID, posting_currency="AUD"
    )
    payload = build_accpay_draft_payload(txn, contact_id="contact-1")
    assert "DueDate" not in payload


@pytest.mark.asyncio
async def test_export_currency_missing_document_blocks_without_500(db_session):
    """Missing document currency => controlled blocking error, not HTTP 500."""
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session, currency="")
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_missing" in codes
    assert result["valid"] is False
    assert result["canonical"] is not None
    assert result["canonical"]["currency"] == ""


@pytest.mark.asyncio
async def test_successful_export_idempotent_and_attachment_retry(db_session, tmp_path):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_SUPPLIER,
        source_key="acme-supplies",
        external_id="contact-1",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )

    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    inv.raw_file_path = str(pdf)
    await db_session.flush()

    mock_client = MagicMock()
    mock_client.post_json = AsyncMock(
        return_value={
            "Invoices": [
                {
                    "InvoiceID": "xero-inv-1",
                    "InvoiceNumber": "INV-100",
                    "Status": "DRAFT",
                    "CurrencyCode": "AUD",
                    "Total": "110.00",
                }
            ]
        }
    )
    mock_client.put_bytes = AsyncMock(
        return_value=MagicMock(
            content=b'{"Attachments":[{"AttachmentID":"att-1"}]}',
            json=lambda: {"Attachments": [{"AttachmentID": "att-1"}]},
        )
    )

    with (
        patch(
            "app.services.integration.xero.xero_export_service.require_xero_ready",
            AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
        ),
        patch(
            "app.services.integration.xero.xero_export_service.XeroClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.integration.xero.xero_attachment_service.XeroClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.integration.xero.xero_attachment_service.open_pdf_for_reading",
        ) as open_pdf,
    ):
        from contextlib import contextmanager

        @contextmanager
        def _open(_path, **_kwargs):
            yield pdf

        open_pdf.side_effect = lambda *a, **k: _open(*a, **k)

        first = await export_supplier_invoice_to_xero(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            user_id=1,
        )
        assert first["skipped"] is False
        assert first["evidence"]["status"] == STATUS_SUCCESS
        assert first["evidence"]["external_id"] == "xero-inv-1"
        assert first["xero_payload"]["Status"] == "DRAFT"
        assert first["xero_payload"]["Type"] == "ACCPAY"
        assert mock_client.post_json.await_count == 1

        second = await export_supplier_invoice_to_xero(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            user_id=1,
        )
        assert second["skipped"] is True
        assert mock_client.post_json.await_count == 1  # no duplicate bill

        # Force attachment failed then retry without new invoice
        ledger = (
            await db_session.execute(
                select(AccountingExportLedger).where(
                    AccountingExportLedger.source_invoice_id == inv.id
                )
            )
        ).scalar_one()
        ledger.attachment_status = "failed"
        await db_session.flush()
        retry = await retry_attachment(
            db_session, tenant_id=TESTING_TENANT_UUID, sync_id=ledger.id
        )
        assert retry["evidence"]["attachment_status"] == ATTACHMENT_SUCCESS
        assert mock_client.post_json.await_count == 1


@pytest.mark.asyncio
async def test_transient_retry_vs_terminal(db_session):
    await _seed_xero_ready(db_session)
    inv = await _seed_invoice(db_session)
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_SUPPLIER,
        source_key="acme-supplies",
        external_id="contact-1",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )

    mock_client = MagicMock()
    mock_client.post_json = AsyncMock(
        side_effect=XeroApiError(status_code=503, error_code="unavailable", message="down")
    )
    with (
        patch(
            "app.services.integration.xero.xero_export_service.require_xero_ready",
            AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
        ),
        patch(
            "app.services.integration.xero.xero_export_service.XeroClient",
            return_value=mock_client,
        ),
    ):
        from app.services.integration.xero.xero_export_service import XeroExportError

        with pytest.raises(XeroExportError) as exc:
            await export_supplier_invoice_to_xero(
                db_session,
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=inv.id,
                user_id=1,
            )
        assert exc.value.bucket == ERROR_TRANSIENT
        ledger = (
            await db_session.execute(select(AccountingExportLedger))
        ).scalar_one()
        assert ledger.status == STATUS_RETRY_PENDING

    mock_client.post_json = AsyncMock(
        side_effect=XeroApiError(
            status_code=400, error_code="ValidationException", message="bad tax"
        )
    )
    with (
        patch(
            "app.services.integration.xero.xero_export_service.require_xero_ready",
            AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
        ),
        patch(
            "app.services.integration.xero.xero_export_service.XeroClient",
            return_value=mock_client,
        ),
    ):
        from app.services.integration.xero.xero_export_service import XeroExportError

        with pytest.raises(XeroExportError):
            await export_supplier_invoice_to_xero(
                db_session,
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=inv.id,
                user_id=1,
            )
        ledger = (
            await db_session.execute(
                select(AccountingExportLedger).order_by(AccountingExportLedger.id.desc())
            )
        ).scalars().first()
        assert ledger.status == STATUS_FAILED_TERMINAL


@pytest.mark.asyncio
async def test_ambiguous_supplier_human_review(db_session):
    integration = await _seed_xero_ready(db_session)
    db_session.add(
        XeroContact(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            xero_contact_id="contact-dup",
            name="Twin Co",
            sync_status="active",
        )
    )
    db_session.add(
        XeroContact(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="xero-org-1",
            xero_contact_id="contact-dup-2",
            name="Twin Co",
            sync_status="active",
        )
    )
    inv = await _seed_invoice(db_session, vendor="Twin Co", abn=None)
    inv.email_sender = None
    await db_session.flush()
    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="xero-org-1",
    )
    with patch(
        "app.services.integration.xero.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="xero-org-1"), "xero-org-1")),
    ):
        from app.services.integration.xero.xero_export_service import XeroExportError

        with pytest.raises(XeroExportError) as exc:
            await export_supplier_invoice_to_xero(
                db_session,
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=inv.id,
                user_id=1,
            )
        assert exc.value.code == "ambiguous_supplier_match"
        assert exc.value.ledger is not None
        assert exc.value.ledger.status == STATUS_HUMAN_REVIEW


def test_payload_hash_stable():
    a = CanonicalAccountingTransaction(
        qll_transaction_id="q",
        tenant_id="t",
        source_invoice_id=1,
        currency="AUD",
        supplier=CanonicalSupplier(legal_name="A"),
        lines=[
            CanonicalLine(
                line_id="1",
                description="d",
                quantity=1,
                unit_price=1,
                line_amount=1,
            )
        ],
        subtotal=Decimal("1"),
        tax_total=Decimal("0"),
        total=Decimal("1"),
        idempotency_key="k",
    )
    h1 = compute_payload_hash(a)
    h2 = compute_payload_hash(a)
    assert h1 == h2
