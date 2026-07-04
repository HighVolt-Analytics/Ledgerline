"""Tests for unified rule book account mapping."""

import pytest

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.rule_book.account_mapper import (
    clear_rule_book_cache,
    get_tax_account_mapping,
    map_to_account,
    map_with_details,
)
from app.services.rule_book.rule_book_mapper import (
    DOCUMENT_TYPE_RULE_TYPE,
    FALLBACK_RULE_TYPE,
    clear_classification_config_cache,
)
from app.tenant_ids import TESTING_TENANT_UUID
from tests.rule_book_fixtures import load_capture_config
from tests.rule_book_test_helpers import demo_rule_book_config, mapping_doc_type_config


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()
    clear_rule_book_cache()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_atlassian_maps_via_document_type_post_to() -> None:
    config = mapping_doc_type_config(
        demo_rule_book_config(),
        code="DT-SW",
        ledger="Software Subscription Expense",
        route_target="Expenses Management",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-2026-55721",
        route_target="Expenses Management",
        document_type_code="DT-SW",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = await map_to_account(inv, config=config)
    assert mapping.account_code == "6120"
    assert mapping.account_name == "Software Subscription Expense"


@pytest.mark.asyncio
async def test_aws_maps_to_cloud_hosting() -> None:
    config = load_capture_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Purchase Management",
        document_type_code="DT-01",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = await map_to_account(inv, config=config)
    assert mapping.account_code == "6110"
    assert mapping.account_name == "Cloud Hosting Expense"


@pytest.mark.asyncio
async def test_marketing_po_maps_via_document_type() -> None:
    config = mapping_doc_type_config(
        demo_rule_book_config(),
        code="DT-MKT",
        ledger="Marketing Expense",
        route_target="Purchase Management",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Atlassian Pty Ltd",
        invoice_no="INV PO-MKT-2026-014",
        po_reference="PO-MKT-2026-014",
        route_target="Purchase Management",
        document_type_code="DT-MKT",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = await map_to_account(inv, config=config)
    assert mapping.account_name == "Marketing Expense"
    assert mapping.account_code == "6130"


@pytest.mark.asyncio
async def test_unknown_vendor_uses_fallback() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier Pty Ltd",
        invoice_no="X-1",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    config = demo_rule_book_config()
    mapping = await map_to_account(inv, config=config)
    assert mapping.account_code == "9999"
    assert mapping.account_name == "Suspense Account"


@pytest.mark.asyncio
async def test_tax_account_from_posting_defaults() -> None:
    config = demo_rule_book_config()
    tax = await get_tax_account_mapping(tenant_id=TESTING_TENANT_UUID, config=config)
    assert tax.account_code == "1400"
    assert tax.account_name == "GST Paid"


@pytest.mark.asyncio
async def test_unclassified_invoice_uses_fallback() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Generic Supplier",
        invoice_no="DOC-2026-00042",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    config = demo_rule_book_config()
    mapping = await map_to_account(inv, config=config)
    assert mapping.account_code == "9999"
    assert mapping.account_name == "Suspense Account"


@pytest.mark.asyncio
async def test_marketing_po_detail_includes_document_type_rule() -> None:
    config = mapping_doc_type_config(
        demo_rule_book_config(),
        code="DT-MKT",
        ledger="Marketing Expense",
        route_target="Purchase Management",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Google Australia Pty Ltd",
        invoice_no="GOOG-AU-99102",
        po_reference="PO-MKT-2026-014",
        route_target="Purchase Management",
        document_type_code="DT-MKT",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = await map_with_details(inv, config=config)
    assert detail.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert detail.account_name == "Marketing Expense"


@pytest.mark.asyncio
async def test_fallback_rule_type_for_unclassified_invoice() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Generic Supplier",
        invoice_no="DOC-2026-00042",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = await map_with_details(inv, config=demo_rule_book_config())
    assert detail.rule_type == FALLBACK_RULE_TYPE
