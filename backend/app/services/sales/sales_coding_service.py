"""Sales coding from document-type Post to."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.models.sales_order import SalesOrder
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


def apply_post_to_to_so(
    so: SalesOrder,
    post: PostToAccounts,
    *,
    document_type_code: str | None = None,
) -> None:
    so.ledger = post.ledger
    so.sub_ledger = (post.sub_ledger or "").strip() or None
    so.tax_account = post.tax_account or "GST Collected"
    so.receivable_account = post.receivable_account or "Accounts Receivable"
    so.sales_rule_id = (document_type_code or "").strip() or None


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
) -> bool:
    """Apply document-type Post to coding on the SO."""
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if definition is None:
        return False
    post_accounts = definition.post_to.as_post_to_accounts()
    if post_accounts is None:
        return False
    apply_post_to_to_so(so, post_accounts, document_type_code=definition.code)
    return True


def inherit_so_coding_to_invoice(
    so: SalesOrder,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
) -> bool:
    """Apply SO ledger to invoice when SO was coded from document type."""
    ledger = (so.ledger or "").strip()
    if not ledger:
        return False
    mapping = _ledger_to_mapping(ledger, config)
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    return True
