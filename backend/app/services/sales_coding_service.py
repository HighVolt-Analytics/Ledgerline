"""Sales rule coding and SO → invoice inheritance."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.models.sales_order import SalesOrder
from app.schemas.rule_book_config import PostToAccounts, RuleBookConfigPayload, SalesRule
from app.services.account_mapper import AccountMapping, resolve_category_for_config
from app.services.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_engine import match_sales_rule


def _ledger_to_mapping(
    ledger: str,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    resolved = resolve_category_for_config(ledger, config)
    return AccountMapping(
        account_code=resolved.account_code,
        account_name=resolved.account_name,
        expense_category=ledger,
    )


def apply_post_to_to_so(so: SalesOrder, rule: SalesRule) -> None:
    post = rule.post_to
    so.ledger = post.ledger
    so.sub_ledger = (post.sub_ledger or "").strip() or None
    so.tax_account = post.tax_account or "GST Collected"
    so.receivable_account = post.receivable_account or "Accounts Receivable"
    so.sales_rule_id = rule.id


def apply_post_to_to_invoice(
    invoice: Invoice,
    post: PostToAccounts,
    *,
    config: RuleBookConfigPayload | None = None,
) -> None:
    mapping = _ledger_to_mapping(post.ledger, config)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name


def code_so_from_invoice(
    so: SalesOrder,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> SalesRule | None:
    """Match sales rule on invoice and persist coding on the SO."""
    doc = invoice_to_eval_document(invoice)
    rule = match_sales_rule(doc, config.sales_rules)
    if rule is None:
        return None
    apply_post_to_to_so(so, rule)
    return rule


def inherit_so_coding_to_invoice(
    so: SalesOrder,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
) -> bool:
    """Apply SO ledger to invoice when SO was coded by Sales Management book."""
    ledger = (so.ledger or "").strip()
    if not ledger:
        return False
    mapping = _ledger_to_mapping(ledger, config)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    return True
