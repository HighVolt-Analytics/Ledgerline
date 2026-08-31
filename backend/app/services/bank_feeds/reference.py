"""Resolve user-facing bank statement reference text (not unique txn ids)."""

from __future__ import annotations

from app.models.bank_feed import BankTransaction

_STATEMENT_REFERENCE_KEY = "statement_reference"


def statement_reference_from_flags(
    review_flags: dict | list | None,
) -> str | None:
    if not isinstance(review_flags, dict):
        return None
    raw = review_flags.get(_STATEMENT_REFERENCE_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def resolve_txn_reference(txn: BankTransaction) -> str | None:
    """Prefer CSV statement reference; fall back to aggregator external_id."""
    from_flags = statement_reference_from_flags(txn.review_flags)
    if from_flags:
        return from_flags
    if txn.external_id and str(txn.external_id).strip():
        return str(txn.external_id).strip()
    return None


def with_statement_reference(
    review_flags: dict | None,
    reference: str | None,
) -> dict | None:
    """Merge statement_reference into review_flags for CSV imports."""
    flags = dict(review_flags) if review_flags else {}
    if reference and reference.strip():
        flags[_STATEMENT_REFERENCE_KEY] = reference.strip()
    return flags or None
