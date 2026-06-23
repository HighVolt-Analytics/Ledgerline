"""Unified rule book drives invoice mapping."""

import json
from pathlib import Path

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
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.tenant_ids import TESTING_TENANT_UUID


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
    fixture = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    return validate_rule_book_config_payload(json.loads(fixture.read_text(encoding="utf-8")))


def test_rule_match_reason_avoids_doubled_prefix() -> None:
    from app.services.rule_book_mapper import _rule_match_reason

    assert _rule_match_reason("Expense rule", "Expense rule: Telstra") == "Expense rule: Telstra"
    assert _rule_match_reason("Expense rule", "Telstra") == "Expense rule: Telstra"


def test_purchase_rule_maps_before_fallback() -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, config)
    assert hit is not None
    assert hit.rule_type == "Purchase rule"
    assert hit.mapping.account_name == "Cloud Hosting Expense"
    assert hit.mapping.account_code == "6110"


def test_expense_rule_maps_from_line_descriptions() -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-999",
        route_target="Expenses Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    inv.line_items = [
        LineItem(description="AWS EC2 usage", qty=1, unit_price=100, amount=100),
    ]
    mapping = map_invoice_to_account(inv, config=config)
    assert mapping.account_name == "Cloud Hosting Expense"
    assert mapping.account_code == "6110"


def test_config_fallback_when_no_rule_matches() -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier Pty Ltd",
        invoice_no="X-1",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = map_invoice_with_details(inv, config=config)
    assert detail.rule_type == FALLBACK_RULE_TYPE
    assert detail.account_name == "Suspense Account"
    assert detail.account_code == "9999"


def test_atlassian_maps_via_expense_rule() -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-2026-55721",
        route_target="Expenses Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    mapping = map_invoice_to_account(inv, config=config)
    assert mapping.account_code == "6120"
    assert mapping.account_name == "Software Subscription Expense"


def test_marketing_po_uses_purchase_rule() -> None:
    config = _config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Google Australia Pty Ltd",
        invoice_no="GOOG-AU-99102",
        po_reference="PO-MKT-2026-014",
        route_target="Purchase Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    detail = map_invoice_with_details(inv, config=config)
    assert detail.rule_type == "Purchase rule"
    assert detail.account_name == "Marketing Expense"
    assert detail.account_code == "6130"
