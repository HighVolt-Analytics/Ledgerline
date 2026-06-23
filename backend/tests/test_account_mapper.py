"""Tests for unified rule book account mapping."""

import pytest

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.account_mapper import (
    clear_rule_book_cache,
    get_tax_account_mapping,
    map_to_account,
    map_with_details,
)
from app.services.rule_book_mapper import clear_classification_config_cache


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()
    clear_rule_book_cache()
    get_settings.cache_clear()


def test_atlassian_maps_to_software_subscription() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-2026-55721",
        route_target="Expenses Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_to_account(inv)
    assert mapping.account_code == "6120"
    assert mapping.account_name == "Software Subscription Expense"


def test_aws_maps_to_cloud_hosting() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_to_account(inv)
    assert mapping.account_code == "6110"
    assert mapping.account_name == "Cloud Hosting Expense"


def test_po_code_in_invoice_no_uses_purchase_rule() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Atlassian Pty Ltd",
        invoice_no="INV PO-MKT-2026-014",
        po_reference="PO-MKT-2026-014",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_to_account(inv)
    assert mapping.account_name == "Marketing Expense"
    assert mapping.account_code == "6130"


def test_unknown_vendor_uses_fallback() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Unknown Supplier Pty Ltd",
        invoice_no="X-1",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_to_account(inv)
    assert mapping.account_code == "9999"
    assert mapping.account_name == "Suspense Account"


def test_tax_account_from_posting_defaults() -> None:
    tax = get_tax_account_mapping(1)
    assert tax.account_code == "1400"
    assert tax.account_name == "GST Paid"


def test_doc_number_series_maps_to_operating_expenses() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Generic Supplier",
        invoice_no="DOC-2026-00042",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_to_account(inv)
    assert mapping.account_code == "6100"
    assert mapping.account_name == "Operating Expenses"


def test_marketing_po_detail_includes_rule_type() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Google Australia Pty Ltd",
        invoice_no="GOOG-AU-99102",
        po_reference="PO-MKT-2026-014",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = map_with_details(inv)
    assert detail.rule_type == "Purchase rule"
    assert detail.account_name == "Marketing Expense"
