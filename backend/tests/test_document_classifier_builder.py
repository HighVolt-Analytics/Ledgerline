"""Parity tests for frontend documentClassifierBuilder signal definitions."""

from app.services.rule_engine import eval_condition_group_generic


def _resolver(values: dict[str, str]):
    return lambda field: values.get(field, "")


def test_supporting_po_signals_match_po_heading_not_invoice():
    from app.services.document_type_rule_engine import _document_field, build_document_classifier_context
    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.invoice_data import InvoiceData

    # Built tree equivalent to purchase_order template defaults
    root = {
        "type": "group",
        "operator": "AND",
        "children": [
            {
                "type": "group",
                "operator": "OR",
                "children": [
                    {"type": "condition", "field": "has_heading_po", "operator": "equals", "value": "true"},
                    {"type": "condition", "field": "document_text", "operator": "regex", "value": "(?i)purchase order"},
                ],
            },
            {"type": "condition", "field": "has_invoice_no", "operator": "equals", "value": "false"},
            {"type": "condition", "field": "is_commercial_invoice", "operator": "equals", "value": "false"},
        ],
    }
    inv = Invoice(id=1, org_id=1, status=InvoiceStatus.PARSING, currency="AUD")
    parsed = InvoiceData(document_text="PURCHASE ORDER\nPO 12345")
    ctx = build_document_classifier_context(invoice=inv, parsed=parsed)
    resolver = lambda f: _document_field(ctx, f)
    assert eval_condition_group_generic(root, field_resolver=resolver) is True


def test_expense_claim_signal_matches_meal_text():
    root = {
        "type": "group",
        "operator": "OR",
        "children": [
            {
                "type": "condition",
                "field": "document_text",
                "operator": "regex",
                "value": "(?i)(expense[_-]?claim|reimburse|team\\s+lunch|\\bmeal\\b)",
            },
        ],
    }
    body = "Site supervisor team lunch meal  $24.50"
    assert (
        eval_condition_group_generic(
            root,
            field_resolver=_resolver({"document_text": body}),
        )
        is True
    )
