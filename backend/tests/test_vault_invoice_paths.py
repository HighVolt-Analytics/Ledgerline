"""Tests for vault document-type folder resolution."""

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import ROUTE_VAULT
from app.services.vault.vault_invoice_paths import (
    vault_document_type_folder_for_invoice,
    vault_type_folder_from_llm_or_heading,
)
from app.services.vault.vault_paths import ROUTE_PURCHASE, ROUTE_UNROUTED, vault_document_type_segment
from app.services.prompt_registry.catalog import catalog_default_body
from app.tenant_ids import TESTING_TENANT_UUID


def test_vault_document_type_segment_only_for_vault_route() -> None:
    assert vault_document_type_segment(ROUTE_VAULT, "DT-06", short_title="Proforma / advance")
    assert vault_document_type_segment(ROUTE_PURCHASE, "DT-01", short_title="Invoice") is None


def test_vault_document_type_folder_for_invoice_without_catalog() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_VAULT,
        document_type_code="DT-25",
    )
    folder = vault_document_type_folder_for_invoice(inv, [])
    assert folder == "DT-25"


def test_same_canonical_type_same_folder_for_different_headings() -> None:
    inv_a = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_UNROUTED,
        document_heading="GRN",
        extracted_fields={"canonical_document_type": "Goods Receipt Note"},
    )
    inv_b = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_UNROUTED,
        document_heading="Goods Receipt Note",
        extracted_fields={"canonical_document_type": "Goods Receipt Note"},
    )
    assert vault_document_type_folder_for_invoice(inv_a, []) == vault_document_type_folder_for_invoice(
        inv_b, []
    )
    assert vault_document_type_folder_for_invoice(inv_a, []) == "Goods Receipt Note"


def test_heading_fallback_when_canonical_empty() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_UNROUTED,
        document_heading="TAX INVOICE",
        extracted_fields={},
    )
    assert vault_type_folder_from_llm_or_heading(inv) == "Tax Invoice"
    assert vault_document_type_folder_for_invoice(inv, []) == "Tax Invoice"


def test_packing_list_case_variants_same_folder() -> None:
    inv_caps = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_UNROUTED,
        document_heading="PACKING LIST",
        extracted_fields={},
    )
    inv_title = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_UNROUTED,
        document_heading="Packing List",
        extracted_fields={"canonical_document_type": "Packing List"},
    )
    assert vault_type_folder_from_llm_or_heading(inv_caps) == "Packing List"
    assert vault_type_folder_from_llm_or_heading(inv_title) == "Packing List"
    assert vault_document_type_folder_for_invoice(inv_caps, []) == (
        vault_document_type_folder_for_invoice(inv_title, [])
    )


def test_vault_unclassified_when_no_heading_on_vault_book() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=ROUTE_VAULT,
    )
    assert vault_document_type_folder_for_invoice(inv, []) == "Unclassified"


def test_header_extract_prompt_includes_canonical_and_edge_cases() -> None:
    body = catalog_default_body("vision.header_extract.system") or ""
    assert "canonical_document_type" in body
    assert "Synonym" in body or "synonym" in body.lower() or "GRN" in body
    assert "document_heading" in body
    assert "invoice_date" in body
    assert "total" in body
    assert "currency" in body
