
from app.tenant_ids import TESTING_TENANT_UUID
"""Sales Management rule book routing and GL mapping."""

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import (
    PostToAccounts,
    SalesMatchOn,
    SalesRule,
    validate_rule_book_config_payload,
)
from app.services.invoice.invoice_evaluation_service import (
    ROUTE_PURCHASE,
    ROUTE_SALES,
    evaluate_invoice_routing,
)
from app.services.rule_book.rule_book_mapper import DOCUMENT_TYPE_RULE_TYPE, resolve_config_mapping
from app.models.sales_order import SalesOrder
from app.services.rule_book.rule_engine import EvalDocument, match_sales_rule
from tests.rule_book_test_helpers import demo_rule_book_config, mapping_doc_type_config


def _rule(**kwargs) -> SalesRule:
    defaults = {
        "id": "sr-test",
        "name": "Test sales rule",
        "enabled": True,
        "priority": 100,
        "match_on": SalesMatchOn(customer_contains="Acme Retail"),
        "post_to": PostToAccounts(
            ledger="Operating Expenses",
            sub_ledger="Product Sales",
            tax_account="GST Paid",
            receivable_account="Accounts Receivable",
        ),
    }
    defaults.update(kwargs)
    return SalesRule(**defaults)


def test_sales_rule_requires_customer_match() -> None:
    rules = [_rule()]
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-100",
        vendor="Acme Retail Pty Ltd",
        document_type="invoice",
    )
    assert match_sales_rule(doc, rules) is not None

    no_match = EvalDocument(
        id="2",
        doc_number="DOC-2",
        invoice_no="INV-200",
        vendor="Other Customer",
        document_type="invoice",
    )
    assert match_sales_rule(no_match, rules) is None


def test_sales_rule_requires_at_least_one_match_field() -> None:
    rules = [_rule(match_on=SalesMatchOn())]
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Acme Retail",
        document_type="invoice",
    )
    assert match_sales_rule(doc, rules) is None


def test_evaluate_invoice_routing_sales_rule_sets_route_target() -> None:
    config = validate_rule_book_config_payload(
        {
            "schema_version": 1,
            "sales_rules": [
                _rule().model_dump(),
            ],
        }
    )
    invoice = Invoice(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Retail Group",
        invoice_no="INV-900",
        status=InvoiceStatus.PENDING,
    )
    result = evaluate_invoice_routing(invoice, config)
    assert result.route_target == ROUTE_SALES
    assert any(mid.startswith("sales:") for mid in result.matched_rule_ids)


def test_resolve_config_mapping_uses_document_type_post_to() -> None:
    config = mapping_doc_type_config(
        demo_rule_book_config(),
        code="DT-SALES",
        ledger="Operating Expenses",
        route_target=ROUTE_SALES,
    )
    invoice = Invoice(
        id=2,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Beta Corp",
        document_ref="DOC-S-44",
        route_target=ROUTE_SALES,
        document_type_code="DT-SALES",
        total=Decimal("120.00"),
        status=InvoiceStatus.PROCESSED,
    )
    hit = resolve_config_mapping(invoice, config)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Operating Expenses"


def test_dt26_high_confidence_routes_to_sales() -> None:
    config = validate_rule_book_config_payload({"schema_version": 1})
    invoice = Invoice(
        id=3,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="INV-OUT-1",
        document_type_code="DT-26",
        document_type_confidence=0.92,
        status=InvoiceStatus.PENDING,
    )
    result = evaluate_invoice_routing(invoice, config)
    assert result.route_target == ROUTE_SALES
    assert "dt:DT-26" in result.matched_rule_ids


def test_perspective_sales_seller_org_routes_to_sales() -> None:
    config = validate_rule_book_config_payload(
        {
            "schema_version": 1,
            "org_context": {
                "legalName": "Acme Hospitality Pty Ltd",
                "defaultPerspective": "seller",
            },
        }
    )
    invoice = Invoice(
        id=4,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="INV-OUT-2",
        extracted_fields={"perspective": "sales", "llm_perspective": "sales"},
        status=InvoiceStatus.PENDING,
    )
    result = evaluate_invoice_routing(invoice, config)
    assert result.route_target == ROUTE_SALES
    assert "perspective:sales" in result.matched_rule_ids


def test_buyer_org_purchase_perspective_does_not_route_to_sales() -> None:
    config = validate_rule_book_config_payload(
        {
            "schema_version": 1,
            "org_context": {
                "legalName": "Acme Hospitality Pty Ltd",
                "defaultPerspective": "buyer",
            },
        }
    )
    invoice = Invoice(
        id=5,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Office Supplies Co",
        invoice_no="INV-IN-1",
        extracted_fields={"perspective": "purchase", "llm_perspective": "purchase"},
        status=InvoiceStatus.PENDING,
    )
    result = evaluate_invoice_routing(invoice, config)
    assert result.route_target != ROUTE_SALES
    assert "perspective:sales" not in result.matched_rule_ids


def test_resolve_config_mapping_uses_document_type_not_sales_order() -> None:
    config = mapping_doc_type_config(
        demo_rule_book_config(),
        code="DT-AR",
        ledger="Operating Expenses",
        route_target=ROUTE_SALES,
    )
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-DEMO-100",
        ledger="Operating Revenue",
        sub_ledger="Room Sales",
    )
    invoice = Invoice(
        id=6,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-DEMO-100",
        route_target=ROUTE_SALES,
        document_type_code="DT-AR",
        total=Decimal("1100.00"),
        status=InvoiceStatus.PROCESSED,
    )
    hit = resolve_config_mapping(invoice, config, sales_order=so)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Operating Expenses"
