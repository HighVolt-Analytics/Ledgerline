
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for vault document-type folder resolution."""

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_evaluation_service import ROUTE_VAULT
from app.services.vault_invoice_paths import vault_document_type_folder_for_invoice
from app.services.vault_paths import ROUTE_PURCHASE, vault_document_type_segment


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
