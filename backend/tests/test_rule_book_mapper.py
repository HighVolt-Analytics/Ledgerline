"""Unified rule book drives invoice mapping via document-type Post to."""

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.classification.document_type_post_to_service import DocumentTypePostToMissingError
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.rule_book.rule_book_mapper import (
    DOCUMENT_TYPE_RULE_TYPE,
    FALLBACK_RULE_TYPE,
    clear_classification_config_cache,
    map_invoice_to_account,
    map_invoice_with_details,
    resolve_config_mapping,
)
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.tenant_ids import TESTING_TENANT_UUID
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


def _config():
    fixture = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    return validate_rule_book_config_payload(json.loads(fixture.read_text(encoding="utf-8")))


def test_document_type_maps_before_fallback() -> None:
    config = mapping_doc_type_config(
        _config(),
        code="DT-TEST",
        ledger="Cloud Hosting Expense",
        route_target="Purchase Management",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Purchase Management",
        document_type_code="DT-TEST",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Cloud Hosting Expense"
    assert hit.mapping.account_code == "6110"


def test_document_type_maps_expense_route() -> None:
    config = mapping_doc_type_config(
        _config(),
        code="DT-EXP",
        ledger="Cloud Hosting Expense",
        route_target="Expenses Management",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-999",
        route_target="Expenses Management",
        document_type_code="DT-EXP",
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


def test_transactional_missing_post_to_raises() -> None:
    from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo

    config = demo_rule_book_config()
    config = config.model_copy(
        update={
            "document_types": [
                DocumentTypeDefinition(
                    code="DT-MISSING",
                    title="Missing GL",
                    short_title="Missing GL",
                    klass="Transactional",
                    posting="Yes",
                    one_line="Needs Post to",
                    route_target="Purchase Management",
                    post_to=DocumentTypePostTo(ledger=""),
                )
            ]
        }
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-1",
        route_target="Purchase Management",
        document_type_code="DT-MISSING",
        status=InvoiceStatus.MAPPING,
    )
    with pytest.raises(DocumentTypePostToMissingError):
        resolve_config_mapping(inv, config)


def test_marketing_document_type_mapping() -> None:
    config = mapping_doc_type_config(
        _config(),
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
    detail = map_invoice_with_details(inv, config=config)
    assert detail.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert detail.account_name == "Marketing Expense"
    assert detail.account_code == "6130"
