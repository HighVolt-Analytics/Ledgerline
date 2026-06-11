"""Purchase rule coding and PO → invoice inheritance (architecture §4)."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import PostToAccounts, PurchaseRule, RuleBookConfigPayload
from app.services.account_mapper import AccountMapping, resolve_category
from app.services.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_engine import match_purchase_rule


def _ledger_to_mapping(ledger: str) -> AccountMapping:
    resolved = resolve_category(ledger)
    return AccountMapping(
        account_code=resolved.account_code,
        account_name=resolved.account_name,
        expense_category=ledger,
    )


def apply_post_to_to_po(po: PurchaseOrder, rule: PurchaseRule) -> None:
    post = rule.post_to
    po.ledger = post.ledger
    po.sub_ledger = (post.sub_ledger or "").strip() or None
    po.tax_account = post.tax_account or "GST Paid"
    po.payable_account = post.payable_account or "Accounts Payable"
    po.purchase_rule_id = rule.id


def apply_post_to_to_invoice(invoice: Invoice, post: PostToAccounts) -> None:
    mapping = _ledger_to_mapping(post.ledger)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name


def code_po_from_invoice(
    po: PurchaseOrder,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> PurchaseRule | None:
    """Match purchase rule on invoice and persist coding on the PO."""
    doc = invoice_to_eval_document(invoice)
    rule = match_purchase_rule(doc, config.purchase_rules)
    if rule is None:
        return None
    apply_post_to_to_po(po, rule)
    return rule


def inherit_po_coding_to_invoice(po: PurchaseOrder, invoice: Invoice) -> bool:
    """Apply PO ledger to invoice when PO was coded by Purchase Management book."""
    ledger = (po.ledger or "").strip()
    if not ledger:
        return False
    mapping = _ledger_to_mapping(ledger)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    return True
