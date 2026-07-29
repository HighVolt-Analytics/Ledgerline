"""Resolve document-type Post to GL settings."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_gl_defaults import resolve_coa_account_name
from app.services.master_data.chart_of_accounts_service import (
    ledger_has_sub_ledger_catalog,
    sub_ledger_exists,
)
from app.services.master_data.vendor_registration_policy import resolve_document_type_definition


class DocumentTypePostToMissingError(ValueError):
    """Transactional document type has no valid Post to ledger configured."""


class DocumentTypePostToControlAccountError(ValueError):
    """Transactional Post to must not target AP/AR/bank/control accounts."""


_CONTROL_LEDGER_NAME = re.compile(
    r"\b(payable|receivable|creditor|debtor|suspense|bank|cash)\b",
    re.IGNORECASE,
)


def document_type_requires_post_to(definition: DocumentTypeDefinition | None) -> bool:
    if definition is None or not definition.enabled:
        return False
    return (definition.posting or "").strip().lower() != "no"


def ledger_exists_in_coa(ledger: str, accounts: Sequence[ChartOfAccountEntry]) -> bool:
    cleaned = (ledger or "").strip()
    if not cleaned:
        return False
    return bool(resolve_coa_account_name(cleaned, list(accounts)))


def control_account_names(defaults: PostingDefaults | None) -> set[str]:
    if defaults is None:
        defaults = PostingDefaults()
    names = {
        (defaults.payable_account or "").strip().lower(),
        (defaults.receivable_account or "").strip().lower(),
        (defaults.bank_account or "").strip().lower(),
        (defaults.fallback_account or "").strip().lower(),
    }
    return {name for name in names if name}


def is_control_post_to_ledger(
    ledger: str,
    *,
    posting_defaults: PostingDefaults | None = None,
) -> bool:
    """True when ledger is a control/counterparty account unsuitable as transactional Post To."""
    cleaned = (ledger or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in control_account_names(posting_defaults):
        return True
    return bool(_CONTROL_LEDGER_NAME.search(cleaned))


def sub_ledger_valid_for_post_to(
    ledger: str,
    sub_ledger: str,
    accounts: Sequence[ChartOfAccountEntry],
) -> bool:
    """Soft validation: blank sub-ledger is always valid; when catalog exists, value must match."""
    cleaned_sub = (sub_ledger or "").strip()
    if not cleaned_sub:
        return True
    account_list = list(accounts)
    if not ledger_has_sub_ledger_catalog(ledger, account_list):
        return True
    return sub_ledger_exists(ledger, cleaned_sub, account_list)


def has_valid_document_type_post_to(
    definition: DocumentTypeDefinition | None,
    accounts: Sequence[ChartOfAccountEntry],
    *,
    posting_defaults: PostingDefaults | None = None,
) -> bool:
    if definition is None:
        return False
    if not document_type_requires_post_to(definition):
        return True
    ledger = (definition.post_to.ledger or "").strip()
    if not ledger:
        return False
    if is_control_post_to_ledger(ledger, posting_defaults=posting_defaults):
        return False
    return ledger_exists_in_coa(ledger, accounts)


def resolve_document_type_definition_for_invoice(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> DocumentTypeDefinition | None:
    return resolve_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )


def resolve_document_type_post_to(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> DocumentTypePostTo | None:
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if definition is None:
        return None
    return definition.post_to


def resolve_document_type_post_to_by_code(
    document_type_code: str | None,
    *,
    document_types: Sequence[DocumentTypeDefinition],
) -> DocumentTypePostTo | None:
    definition = get_document_type_definition(
        (document_type_code or "").strip().upper(),
        document_types=document_types,
    )
    if definition is None:
        return None
    return definition.post_to


def ensure_transactional_post_to_or_raise(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> DocumentTypeDefinition | None:
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if not document_type_requires_post_to(definition):
        return definition
    code = (invoice.document_type_code or "").strip().upper() or "?"
    if definition is None:
        raise DocumentTypePostToMissingError(
            f"Document type {code} is not configured — set Post to in Rule Book → Document types."
        )
    ledger = (definition.post_to.ledger or "").strip()
    if not ledger:
        raise DocumentTypePostToMissingError(
            f"Document type {code} has no Post to ledger — configure it in Rule Book → Document types."
        )
    if is_control_post_to_ledger(ledger, posting_defaults=config.posting_defaults):
        raise DocumentTypePostToControlAccountError(
            f"Document type {code} Post to ledger {ledger!r} is a control account "
            "(AP/AR/bank/cash/suspense) — pick an expense or revenue ledger instead."
        )
    if not ledger_exists_in_coa(ledger, config.chart_of_accounts):
        raise DocumentTypePostToMissingError(
            f"Document type {code} Post to ledger {ledger!r} is not in your chart of accounts."
        )
    return definition
