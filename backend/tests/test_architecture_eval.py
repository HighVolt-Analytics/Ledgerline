"""Architecture §2.1 / §2.2 — evaluation sequence and priority."""

from app.schemas.rule_book_config import (
    ExpenseMatchOn,
    ExpenseRule,
    PostToAccounts,
    PurchaseMatchOn,
    PurchaseRule,
    TeamExpenseMatchOn,
    TeamExpensePolicy,
    TeamExpenseRule,
)
from app.services.invoice_evaluation_service import ROUTE_EXPENSES, evaluate_invoice_routing
from app.services.po_reference import is_plausible_po_reference
from app.services.rule_book_mapper import resolve_config_mapping
from app.services.rule_engine import EvalDocument, match_expense_rule, match_purchase_rule
from app.models.invoice import Invoice, InvoiceStatus


def test_is_plausible_po_reference_rejects_ocr_junk() -> None:
    assert not is_plausible_po_reference("the")
    assert not is_plausible_po_reference("ab")
    assert is_plausible_po_reference("PO-DEMO-2001")
    assert is_plausible_po_reference("PO1234")


def test_category_rules_use_priority_first_match_wins() -> None:
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Acme Corp",
        po="PO-TEST-99",
    )
    rules = [
        PurchaseRule(
            id="low",
            name="Low priority",
            enabled=True,
            priority=200,
            match_on=PurchaseMatchOn(
                po_prefix="PO-TEST",
                vendor_contains="Acme",
                invoice_references_po=True,
            ),
            post_to=PostToAccounts(ledger="Raw Materials"),
        ),
        PurchaseRule(
            id="high",
            name="High priority",
            enabled=True,
            priority=100,
            match_on=PurchaseMatchOn(
                po_prefix="PO-TEST",
                invoice_references_po=True,
            ),
            post_to=PostToAccounts(ledger="Cloud Hosting Expense"),
        ),
    ]
    hit = match_purchase_rule(doc, rules)
    assert hit is not None
    assert hit.id == "high"


def test_gl_cascade_expense_before_team() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Local Cafe",
        invoice_no="MEAL-001",
        route_target="Expenses Management",
        status=InvoiceStatus.MAPPING,
    )
    from app.services.rule_book_mapper import load_classification_config

    config = load_classification_config(1)
    expense_rules = [
        *config.expense_rules,
        ExpenseRule(
            id="er-test-cafe",
            name="Cafe meals",
            enabled=True,
            priority=50,
            match_on=ExpenseMatchOn(vendor_contains="Cafe"),
            post_to=PostToAccounts(ledger="Travel Expense"),
        ),
    ]
    team_rules = [
        *config.team_expense_rules,
        TeamExpenseRule(
            id="tr-test-cafe",
            name="Team cafe",
            enabled=True,
            priority=50,
            match_on=TeamExpenseMatchOn(merchant_contains="Cafe"),
            post_to=PostToAccounts(ledger="Staff Meals"),
            policy=TeamExpensePolicy(),
        ),
    ]
    config = config.model_copy(
        update={"expense_rules": expense_rules, "team_expense_rules": team_rules}
    )
    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == "Expense rule"
    assert hit.mapping.account_name == "Travel Expense"


def test_routing_expense_before_team_without_email() -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Local Cafe",
        invoice_no="MEAL-002",
        status=InvoiceStatus.MAPPING,
    )
    from app.services.rule_book_mapper import load_classification_config

    config = load_classification_config(1)
    expense_rules = [
        ExpenseRule(
            id="er-routing",
            name="Cafe routing",
            enabled=True,
            priority=100,
            match_on=ExpenseMatchOn(vendor_contains="Cafe"),
            post_to=PostToAccounts(ledger="Travel Expense"),
        ),
    ]
    team_rules = [
        TeamExpenseRule(
            id="tr-routing",
            name="Team cafe routing",
            enabled=True,
            priority=100,
            match_on=TeamExpenseMatchOn(merchant_contains="Cafe"),
            post_to=PostToAccounts(ledger="Staff Meals"),
            policy=TeamExpensePolicy(),
        ),
    ]
    config = config.model_copy(
        update={"expense_rules": expense_rules, "team_expense_rules": team_rules}
    )
    result = evaluate_invoice_routing(inv, config)
    assert result.route_target == ROUTE_EXPENSES
    assert "expense:er-routing" in result.matched_rule_ids
