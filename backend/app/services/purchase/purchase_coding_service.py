"""Purchase coding from document-type Post to."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import PostToAccounts, RuleBookConfigPayload
from app.services.rule_book.account_mapper import AccountMapping, resolve_category_for_config
from app.services.classification.document_type_post_to_service import (
    resolve_document_type_definition_for_invoice,
)


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


def apply_post_to_to_po(
    po: PurchaseOrder,
    post: PostToAccounts,
    *,
    document_type_code: str | None = None,
) -> None:
    po.ledger = post.ledger
    po.sub_ledger = (post.sub_ledger or "").strip() or None
    po.tax_account = post.tax_account or "GST Paid"
    po.payable_account = post.payable_account or "Accounts Payable"
    po.purchase_rule_id = (document_type_code or "").strip() or None


def apply_post_to_to_invoice(
    invoice: Invoice,
    post: PostToAccounts,
    *,
    config: RuleBookConfigPayload | None = None,
) -> None:
    mapping = _ledger_to_mapping(post.ledger, config)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name


def code_po_from_invoice(
    po: PurchaseOrder,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """Apply document-type Post to coding on the PO."""
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if definition is None:
        return False
    post_accounts = definition.post_to.as_post_to_accounts()
    if post_accounts is None:
        return False
    apply_post_to_to_po(po, post_accounts, document_type_code=definition.code)
    return True


def inherit_po_coding_to_invoice(
    po: PurchaseOrder,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
) -> bool:
    """Apply PO ledger to invoice when PO was coded from document type."""
    ledger = (po.ledger or "").strip()
    if not ledger:
        return False
    mapping = _ledger_to_mapping(ledger, config)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    return True
