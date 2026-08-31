"""Apply bank narration rules to unmatched bank transactions (metadata only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import BankAccount, BankTransaction, BankTxnMatchStatus
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.audit.audit_service import log_event
from app.services.rule_book.rule_book_config_io import load_rule_book_config_with_masters
from app.services.rule_book.rule_engine import match_bank_narration_rule


@dataclass
class CategorizeRunResult:
    transaction_id: int
    categorized: bool
    category_coa: str | None
    rule_id: str | None
    rule_name: str | None


def _category_label(ledger: str, sub_ledger: str | None) -> str:
    ledger = (ledger or "").strip()
    sub = (sub_ledger or "").strip()
    if ledger and sub:
        return f"{ledger} / {sub}"
    return ledger


def _flags_dict(txn: BankTransaction) -> dict[str, Any]:
    flags = txn.review_flags if isinstance(txn.review_flags, dict) else {}
    return dict(flags)


def clear_category_on_match(txn: BankTransaction) -> None:
    """Match-derived category wins — clear live bank category, keep history."""
    flags = _flags_dict(txn)
    if txn.category_coa or flags.get("categorization"):
        flags["superseded_categorization"] = {
            "category_coa": txn.category_coa,
            "categorization": flags.get("categorization"),
        }
        flags.pop("categorization", None)
        txn.review_flags = flags or None
    txn.category_coa = None


async def apply_rule_to_transaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
    rules: list | None = None,
) -> CategorizeRunResult:
    if txn.match_status != BankTxnMatchStatus.UNMATCHED.value:
        return CategorizeRunResult(txn.id, False, txn.category_coa, None, None)

    if rules is None:
        raw = await load_rule_book_config_with_masters(session, tenant_id)
        rules = list(validate_rule_book_config_payload(raw).bank_narration_rules or [])

    hit = match_bank_narration_rule(txn.description or "", rules)
    if hit is None:
        return CategorizeRunResult(txn.id, False, txn.category_coa, None, None)

    category = _category_label(hit.rule.post_to.ledger, hit.rule.post_to.sub_ledger)
    if not category:
        return CategorizeRunResult(txn.id, False, txn.category_coa, None, None)

    flags = _flags_dict(txn)
    existing = flags.get("categorization") if isinstance(flags.get("categorization"), dict) else None
    if (
        txn.category_coa == category
        and existing
        and existing.get("source") == "rule"
        and existing.get("rule_id") == hit.rule.id
    ):
        return CategorizeRunResult(txn.id, False, txn.category_coa, hit.rule.id, hit.rule.name)

    before = txn.category_coa
    flags.pop("superseded_categorization", None)
    flags["categorization"] = {
        "source": "rule",
        "rule_id": hit.rule.id,
        "rule_name": hit.rule.name,
        "matched_on": hit.matched_on,
        "matched_snippet": hit.matched_snippet,
        "ledger": hit.rule.post_to.ledger,
        "sub_ledger": hit.rule.post_to.sub_ledger or "",
    }
    txn.category_coa = category
    txn.review_flags = flags
    await session.flush()
    await log_event(
        session,
        "bank_txn_categorized",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "before_category_coa": before,
            "category_coa": category,
            "rule_id": hit.rule.id,
            "rule_name": hit.rule.name,
            "matched_on": hit.matched_on,
            "matched_snippet": hit.matched_snippet,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return CategorizeRunResult(
        txn.id, True, category, hit.rule.id, hit.rule.name
    )


async def run_categorize_for_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
    only_transaction_ids: list[int] | None = None,
) -> list[CategorizeRunResult]:
    raw = await load_rule_book_config_with_masters(session, tenant_id)
    rules = list(validate_rule_book_config_payload(raw).bank_narration_rules or [])
    stmt = select(BankTransaction).where(
        BankTransaction.tenant_id == tenant_id,
        BankTransaction.bank_account_id == account.id,
        BankTransaction.match_status == BankTxnMatchStatus.UNMATCHED.value,
    )
    if only_transaction_ids is not None:
        if not only_transaction_ids:
            return []
        stmt = stmt.where(BankTransaction.id.in_(only_transaction_ids))
    stmt = stmt.order_by(BankTransaction.txn_date.asc(), BankTransaction.id.asc())
    txns = list((await session.execute(stmt)).scalars().all())
    results: list[CategorizeRunResult] = []
    for txn in txns:
        # Skip if already manually categorized (do not overwrite manual)
        flags = _flags_dict(txn)
        cat = flags.get("categorization") if isinstance(flags.get("categorization"), dict) else None
        if cat and cat.get("source") == "manual" and txn.category_coa:
            results.append(
                CategorizeRunResult(txn.id, False, txn.category_coa, None, None)
            )
            continue
        results.append(
            await apply_rule_to_transaction(
                session,
                tenant_id=tenant_id,
                txn=txn,
                actor_name=actor_name,
                actor_email=actor_email,
                client_ip=client_ip,
                rules=rules,
            )
        )
    return results


async def set_manual_category(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    category_coa: str | None,
    ledger: str | None = None,
    sub_ledger: str | None = None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    if txn.match_status != BankTxnMatchStatus.UNMATCHED.value:
        raise ValueError("Only unmatched bank lines can be categorized manually")

    before = txn.category_coa
    before_flags = _flags_dict(txn).get("categorization")
    cleaned = (category_coa or "").strip() or None
    if cleaned is None and ledger:
        cleaned = _category_label(ledger, sub_ledger)

    flags = _flags_dict(txn)
    if cleaned:
        flags["categorization"] = {
            "source": "manual",
            "rule_id": None,
            "rule_name": None,
            "matched_on": None,
            "matched_snippet": None,
            "ledger": (ledger or cleaned).strip(),
            "sub_ledger": (sub_ledger or "").strip(),
        }
        flags.pop("superseded_categorization", None)
        txn.category_coa = cleaned
        txn.review_flags = flags
    else:
        flags.pop("categorization", None)
        txn.category_coa = None
        txn.review_flags = flags or None

    await session.flush()
    await log_event(
        session,
        "bank_txn_category_overridden",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "before_category_coa": before,
            "before_categorization": before_flags,
            "category_coa": txn.category_coa,
            "categorization": (_flags_dict(txn).get("categorization")),
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await session.refresh(txn)
    return txn
