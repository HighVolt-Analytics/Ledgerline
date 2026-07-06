"""Resolve document-type Post to GL settings."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
from app.schemas.rule_book_config import ChartOfAccountEntry, RuleBookConfigPayload
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_gl_defaults import resolve_coa_account_name
from app.services.master_data.chart_of_accounts_service import (
    ledger_has_sub_ledger_catalog,
    sub_ledger_exists,
)
from app.services.master_data.vendor_registration_policy import resolve_document_type_definition


class DocumentTypePostToMissingError(ValueError):
    """Transactional document type has no valid Post to ledger configured."""


def document_type_requires_post_to(definition: DocumentTypeDefinition | None) -> bool:
    if definition is None or not definition.enabled:
        return False
    return (definition.posting or "").strip().lower() != "no"


def ledger_exists_in_coa(ledger: str, accounts: Sequence[ChartOfAccountEntry]) -> bool:
    cleaned = (ledger or "").strip()
    if not cleaned:
        return False
    return bool(resolve_coa_account_name(cleaned, list(accounts)))


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
) -> bool:
    if definition is None:
        return False
    if not document_type_requires_post_to(definition):
        return True
    ledger = (definition.post_to.ledger or "").strip()
    if not ledger:
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
    if not ledger_exists_in_coa(ledger, config.chart_of_accounts):
        raise DocumentTypePostToMissingError(
            f"Document type {code} Post to ledger {ledger!r} is not in your chart of accounts."
        )
    return definition
