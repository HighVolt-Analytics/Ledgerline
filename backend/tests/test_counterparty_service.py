"""Counterparty resolution — vendor vs customer on invoice.vendor."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.sales.counterparty_service import resolve_counterparty_name, sync_invoice_counterparty
from app.services.extraction.llm_document_service import llm_result_to_invoice_data
from app.services.tenant.tenant_org_context import OrgContext
from app.services.master_data.vendor_name_utils import extract_customer_party_from_text


ORG = OrgContext(
    legal_name="Highvolt Industries Pty Ltd",
    abn="12345678901",
    default_perspective="seller",
)


def test_sales_prefers_buyer_over_seller() -> None:
    resolved = resolve_counterparty_name(
        side="customer",
        org=ORG,
        buyer_name="Harbour View Hotel",
        seller_name="Highvolt Industries Pty Ltd",
        generic_name="Highvolt Industries Pty Ltd",
    )
    assert resolved == "Harbour View Hotel"


def test_purchase_prefers_seller_over_buyer() -> None:
    resolved = resolve_counterparty_name(
        side="vendor",
        org=ORG,
        buyer_name="Highvolt Industries Pty Ltd",
        seller_name="Spectra Innovations Pty Ltd",
        generic_name="Spectra Innovations Pty Ltd",
    )
    assert resolved == "Spectra Innovations Pty Ltd"


def test_extract_customer_party_from_bill_to_block() -> None:
    text = "TAX INVOICE\nBill To\nHarbour View Hotel\n123 Wharf Rd\n"
    assert extract_customer_party_from_text(text) == "Harbour View Hotel"


def test_llm_sales_result_uses_customer_not_tenant_seller() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-28",
        confidence=0.9,
        perspective="sales",
        seller=LlmParty(name="Highvolt Industries Pty Ltd"),
        buyer=LlmParty(name="Harbour View Hotel"),
        vendor="Highvolt Industries Pty Ltd",
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(success=True, text="Bill To\nHarbour View Hotel", text_length=24),
        org=ORG,
    )
    assert parsed.vendor == "Harbour View Hotel"


def test_sync_invoice_counterparty_on_sales_route() -> None:
    inv = Invoice(
        tenant_id=None,  # type: ignore[arg-type]
        vendor="Highvolt Industries Pty Ltd",
        route_target="Sales Management",
        extracted_fields={
            "buyer_name": "Harbour View Hotel",
            "seller_name": "Highvolt Industries Pty Ltd",
            "perspective": "sales",
        },
    )
    sync_invoice_counterparty(inv, config=None, org=ORG)
    assert inv.vendor == "Harbour View Hotel"
