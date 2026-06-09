"""Unified rule book drives invoice mapping."""

import pytest

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.account_mapper import clear_rule_book_cache
from app.services.rule_book_mapper import (
    FALLBACK_RULE_TYPE,
    clear_classification_config_cache,
    map_invoice_to_account,
    map_invoice_with_details,
    resolve_config_mapping,
)
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.schemas.rule_book_config import validate_rule_book_config_payload


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()
    clear_rule_book_cache()
    get_settings.cache_clear()


def _config():
    return validate_rule_book_config_payload(load_rule_book_config_dict(1))


def test_purchase_rule_maps_before_fallback() -> None:
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, _config())
    assert hit is not None
    assert hit.rule_type == "Purchase rule"
    assert hit.mapping.account_name == "Cloud Hosting Expense"
    assert hit.mapping.account_code == "6110"


def test_expense_rule_maps_from_line_descriptions() -> None:
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-999",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    inv.line_items = [
        LineItem(description="AWS EC2 usage", qty=1, unit_price=100, amount=100),
    ]
    mapping = map_invoice_to_account(inv)
    assert mapping.account_name == "Cloud Hosting Expense"
    assert mapping.account_code == "6110"


def test_config_fallback_when_no_rule_matches() -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown Supplier Pty Ltd",
        invoice_no="X-1",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = map_invoice_with_details(inv)
    assert detail.rule_type == FALLBACK_RULE_TYPE
    assert detail.account_name == "Suspense Account"
    assert detail.account_code == "9999"


def test_atlassian_maps_via_expense_rule() -> None:
    inv = Invoice(
        org_id=1,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-2026-55721",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_invoice_to_account(inv)
    assert mapping.account_code == "6120"
    assert mapping.account_name == "Software Subscription Expense"


def test_marketing_po_uses_purchase_rule() -> None:
    inv = Invoice(
        org_id=1,
        vendor="Google Australia Pty Ltd",
        invoice_no="GOOG-AU-99102",
        po_reference="PO-MKT-2026-014",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = map_invoice_with_details(inv)
    assert detail.rule_type == "Purchase rule"
    assert detail.account_name == "Marketing Expense"
    assert detail.account_code == "6130"
