"""Bank statement import (CSV/PDF) into bank_transactions with fingerprint de-dupe."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankAccount,
    BankFeedImport,
    BankFeedImportStatus,
    BankFeedSource,
    BankTransaction,
    BankTxnMatchStatus,
)
from app.services.audit.audit_service import log_event
from app.services.bank_feeds.csv_parser import CsvParseResult, parse_canonical_bank_csv
from app.services.bank_feeds.pdf_parser import parse_bank_statement_pdf
from app.services.bank_feeds.fingerprint import (
    compute_fingerprint,
    file_sha256,
    normalize_description,
)
from app.services.bank_feeds.reference import with_statement_reference


@dataclass
class ImportResult:
    import_row: BankFeedImport
    reused_existing: bool
    accepted_transaction_ids: list[int]
    categorized_count: int = 0


def _near_duplicate_candidates(
    existing: list[BankTransaction],
    *,
    txn_date,
    amount,
    direction: str,
) -> list[BankTransaction]:
    """Same date+amount+direction but different fingerprint (description drift)."""
    hits: list[BankTransaction] = []
    for row in existing:
        if (
            row.txn_date == txn_date
            and row.amount == amount
            and row.direction == direction
        ):
            hits.append(row)
    return hits


def _preferred_date_order_for_account(account: BankAccount):
    from app.services.bank_feeds.parse_common import preferred_date_order_for_currency

    return preferred_date_order_for_currency(account.currency)


def _parse_profile_for_account(account: BankAccount):
    from app.services.bank_feeds.statement_parse_profile import profile_from_account

    return profile_from_account(account)


def _parse_statement_content(
    content: bytes,
    *,
    source: BankFeedSource,
    preferred_date_order=None,
    profile=None,
) -> CsvParseResult:
    if source == BankFeedSource.PDF:
        return parse_bank_statement_pdf(
            content,
            preferred_date_order=preferred_date_order,
            profile=profile,
        )
    result = parse_canonical_bank_csv(
        content,
        preferred_date_order=preferred_date_order,
        profile=profile,
    )
    return CsvParseResult(
        rows=result.rows,
        errors=result.errors,
        extracted_count=len(result.rows),
        candidate_line_count=len(result.rows) + len(result.errors),
        parse_meta=dict(result.parse_meta or {}),
    )


def _initial_error_report(parsed: CsvParseResult) -> dict[str, Any]:
    report: dict[str, Any] = {
        "parse_errors": [_error_dict(e) for e in parsed.errors],
        "extracted_count": parsed.extracted_count,
        "candidate_line_count": parsed.candidate_line_count,
        "skipped_line_count": parsed.skipped_line_count,
    }
    if parsed.parse_meta:
        report["parse_meta"] = parsed.parse_meta
    return report


async def import_canonical_csv(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    content: bytes,
    filename: str | None,
    actor_user_id: int | None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> ImportResult:
    return await import_statement(
        session,
        tenant_id=tenant_id,
        account=account,
        content=content,
        filename=filename,
        source=BankFeedSource.CSV,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )


def _should_reuse_import(row: BankFeedImport) -> bool:
    """Only reuse successful prior uploads; failed parses can be retried after parser fixes."""
    if row.status == BankFeedImportStatus.FAILED.value:
        return False
    if row.accepted_count > 0 or row.duplicate_count > 0:
        return True
    return row.status == BankFeedImportStatus.COMPLETED.value


def _reset_import_row(
    import_row: BankFeedImport,
    *,
    filename: str | None,
    source: BankFeedSource,
    actor_user_id: int | None,
) -> None:
    import_row.filename = filename
    import_row.source = source.value
    import_row.status = BankFeedImportStatus.FAILED.value
    import_row.row_count = 0
    import_row.accepted_count = 0
    import_row.duplicate_count = 0
    import_row.error_count = 0
    import_row.error_report = None
    import_row.actor_user_id = actor_user_id


async def import_statement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    account: BankAccount,
    content: bytes,
    filename: str | None,
    source: BankFeedSource,
    actor_user_id: int | None,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> ImportResult:
    digest = file_sha256(content)

    existing_import = (
        await session.execute(
            select(BankFeedImport).where(
                BankFeedImport.tenant_id == tenant_id,
                BankFeedImport.bank_account_id == account.id,
                BankFeedImport.file_sha256 == digest,
            )
        )
    ).scalar_one_or_none()
    if existing_import is not None and _should_reuse_import(existing_import):
        await log_event(
            session,
            "bank_feed_import_idempotent_reuse",
            tenant_id=tenant_id,
            detail={
                "import_id": existing_import.id,
                "bank_account_id": account.id,
                "source": existing_import.source,
                "filename": existing_import.filename,
                "file_sha256": digest,
                "row_count": existing_import.row_count,
                "accepted_count": existing_import.accepted_count,
                "duplicate_count": existing_import.duplicate_count,
                "error_count": existing_import.error_count,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
        return ImportResult(
            import_row=existing_import,
            reused_existing=True,
            accepted_transaction_ids=[],
        )

    retry_import = (
        existing_import
        if existing_import is not None
        and existing_import.status == BankFeedImportStatus.FAILED.value
        else None
    )

    if retry_import is None:
        await log_event(
            session,
            "bank_feed_import_started",
            tenant_id=tenant_id,
            detail={
                "bank_account_id": account.id,
                "source": source.value,
                "filename": filename,
                "file_sha256": digest,
                "byte_length": len(content),
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    else:
        await log_event(
            session,
            "bank_feed_import_retry",
            tenant_id=tenant_id,
            detail={
                "import_id": retry_import.id,
                "bank_account_id": account.id,
                "source": source.value,
                "filename": filename,
                "file_sha256": digest,
                "prior_status": retry_import.status,
                "prior_error_count": retry_import.error_count,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )

    parsed: CsvParseResult = _parse_statement_content(
        content,
        source=source,
        preferred_date_order=_preferred_date_order_for_account(account),
        profile=_parse_profile_for_account(account),
    )
    if retry_import is not None:
        import_row = retry_import
        _reset_import_row(
            import_row,
            filename=filename,
            source=source,
            actor_user_id=actor_user_id,
        )
        import_row.error_count = len(parsed.errors)
        import_row.error_report = _initial_error_report(parsed)
    else:
        import_row = BankFeedImport(
            tenant_id=tenant_id,
            bank_account_id=account.id,
            source=source.value,
            filename=filename,
            file_sha256=digest,
            status=BankFeedImportStatus.FAILED.value,
            row_count=0,
            accepted_count=0,
            duplicate_count=0,
            error_count=len(parsed.errors),
            error_report=_initial_error_report(parsed),
            actor_user_id=actor_user_id,
        )
        session.add(import_row)
    await session.flush()

    if not parsed.rows and parsed.errors:
        import_row.status = BankFeedImportStatus.FAILED.value
        import_row.row_count = 0
        await _log_import_completed(
            session,
            tenant_id=tenant_id,
            import_row=import_row,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
            extra={"parse_only_failure": True},
        )
        await session.flush()
        return ImportResult(
            import_row=import_row,
            reused_existing=False,
            accepted_transaction_ids=[],
        )

    existing_txns = list(
        (
            await session.execute(
                select(BankTransaction).where(
                    BankTransaction.tenant_id == tenant_id,
                    BankTransaction.bank_account_id == account.id,
                )
            )
        ).scalars().all()
    )
    by_fingerprint = {t.fingerprint: t for t in existing_txns}

    accepted_ids: list[int] = []
    duplicate_count = 0
    near_dupe_count = 0
    decision_audits: list[dict[str, Any]] = []

    for row in parsed.rows:
        desc_norm = normalize_description(row.description)
        fingerprint = compute_fingerprint(
            txn_date=row.txn_date,
            amount=row.amount,
            direction=row.direction,
            description_normalized=desc_norm,
        )
        fingerprint_inputs = {
            "txn_date": row.txn_date.isoformat(),
            "amount": f"{row.amount:.2f}",
            "direction": row.direction,
            "description_normalized": desc_norm,
        }

        if fingerprint in by_fingerprint:
            duplicate_count += 1
            prior = by_fingerprint[fingerprint]
            decision_audits.append(
                {
                    "decision": "rejected_duplicate",
                    "reason": "fingerprint",
                    "row_number": row.row_number,
                    "fingerprint": fingerprint,
                    "fingerprint_inputs": fingerprint_inputs,
                    "existing_bank_transaction_id": prior.id,
                }
            )
            await log_event(
                session,
                "bank_txn_duplicate_rejected",
                tenant_id=tenant_id,
                detail={
                    "import_id": import_row.id,
                    "bank_account_id": account.id,
                    "bank_transaction_id": prior.id,
                    "reason": "fingerprint",
                    "fingerprint": fingerprint,
                    "fingerprint_inputs": fingerprint_inputs,
                    "csv_row_number": row.row_number,
                },
                actor_name=actor_name,
                actor_email=actor_email,
                client_ip=client_ip,
            )
            continue

        # CSV Reference is not a unique bank txn id — never put it in external_id.
        # De-dupe for CSV is fingerprint-only; external_id is reserved for
        # aggregator/Plaid feeds that assign a true per-line id.
        review_flags: dict[str, Any] | None = None
        near = _near_duplicate_candidates(
            existing_txns,
            txn_date=row.txn_date,
            amount=row.amount,
            direction=row.direction,
        )
        if near:
            near_dupe_count += 1
            review_flags = {
                "possible_duplicate_of": [t.id for t in near],
            }
        if row.direction_confidence:
            review_flags = dict(review_flags or {})
            review_flags["direction_confidence"] = row.direction_confidence
        if row.extraction_source:
            review_flags = dict(review_flags or {})
            review_flags["extraction_source"] = row.extraction_source
        if row.extraction_confidence:
            review_flags = dict(review_flags or {})
            review_flags["extraction_confidence"] = row.extraction_confidence
        if row.extraction_note:
            review_flags = dict(review_flags or {})
            review_flags["extraction_note"] = row.extraction_note
        review_flags = with_statement_reference(review_flags, row.reference)

        txn = BankTransaction(
            tenant_id=tenant_id,
            bank_account_id=account.id,
            import_id=import_row.id,
            txn_date=row.txn_date,
            posted_date=None,
            description=row.description,
            description_normalized=desc_norm,
            amount=row.amount,
            currency=account.currency,
            direction=row.direction,
            balance=row.balance,
            external_id=None,
            fingerprint=fingerprint,
            match_status=BankTxnMatchStatus.UNMATCHED.value,
            review_flags=review_flags,
        )
        session.add(txn)
        await session.flush()
        accepted_ids.append(txn.id)
        by_fingerprint[fingerprint] = txn
        existing_txns.append(txn)

        await log_event(
            session,
            "bank_txn_accepted",
            tenant_id=tenant_id,
            detail={
                "import_id": import_row.id,
                "bank_account_id": account.id,
                "bank_transaction_id": txn.id,
                "fingerprint": fingerprint,
                "fingerprint_inputs": fingerprint_inputs,
                "csv_row_number": row.row_number,
                "statement_reference": row.reference,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
        if near:
            await log_event(
                session,
                "bank_txn_near_duplicate_flagged",
                tenant_id=tenant_id,
                detail={
                    "import_id": import_row.id,
                    "bank_account_id": account.id,
                    "bank_transaction_id": txn.id,
                    "possible_duplicate_of": (review_flags or {}).get(
                        "possible_duplicate_of"
                    ),
                    "fingerprint": fingerprint,
                    "fingerprint_inputs": fingerprint_inputs,
                    "csv_row_number": row.row_number,
                },
                actor_name=actor_name,
                actor_email=actor_email,
                client_ip=client_ip,
            )

    error_count = len(parsed.errors)
    low_confidence_count = sum(
        1 for row in parsed.rows if row.direction_confidence == "low"
    )
    low_extraction_confidence_count = sum(
        1 for row in parsed.rows if row.extraction_confidence == "low"
    )
    import_row.row_count = max(parsed.extracted_count, len(parsed.rows)) + error_count
    import_row.accepted_count = len(accepted_ids)
    import_row.duplicate_count = duplicate_count
    import_row.error_count = error_count
    import_row.error_report = {
        "parse_errors": [_error_dict(e) for e in parsed.errors],
        "near_duplicate_count": near_dupe_count,
        "dedupe_decisions_sample": decision_audits[:50],
        "extracted_count": parsed.extracted_count,
        "candidate_line_count": parsed.candidate_line_count,
        "skipped_line_count": parsed.skipped_line_count,
        "low_direction_confidence_count": low_confidence_count,
        "low_extraction_confidence_count": low_extraction_confidence_count,
        **({"parse_meta": parsed.parse_meta} if parsed.parse_meta else {}),
    }
    if (error_count and accepted_ids) or (
        (low_confidence_count or low_extraction_confidence_count) and accepted_ids
    ):
        import_row.status = BankFeedImportStatus.PARTIAL.value
    elif accepted_ids or (not parsed.rows and not error_count):
        import_row.status = BankFeedImportStatus.COMPLETED.value
    elif duplicate_count and not accepted_ids and not error_count:
        import_row.status = BankFeedImportStatus.COMPLETED.value
    else:
        import_row.status = (
            BankFeedImportStatus.PARTIAL.value
            if accepted_ids
            else BankFeedImportStatus.FAILED.value
        )

    await _log_import_completed(
        session,
        tenant_id=tenant_id,
        import_row=import_row,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
        extra={"near_duplicate_count": near_dupe_count},
    )

    categorized_count = 0
    if accepted_ids:
        from app.services.bank_feeds import categorize_service

        cat_results = await categorize_service.run_categorize_for_account(
            session,
            tenant_id=tenant_id,
            account=account,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
            only_transaction_ids=accepted_ids,
        )
        categorized_count = sum(1 for r in cat_results if r.categorized)
        report = dict(import_row.error_report or {})
        report["categorized_count"] = categorized_count
        import_row.error_report = report

    await session.flush()
    return ImportResult(
        import_row=import_row,
        reused_existing=False,
        accepted_transaction_ids=accepted_ids,
        categorized_count=categorized_count,
    )


def _error_dict(err) -> dict[str, Any]:
    return {
        "row_number": err.row_number,
        "message": err.message,
        "raw": err.raw,
    }


async def _log_import_completed(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    import_row: BankFeedImport,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    detail: dict[str, Any] = {
        "import_id": import_row.id,
        "bank_account_id": import_row.bank_account_id,
        "source": import_row.source,
        "filename": import_row.filename,
        "file_sha256": import_row.file_sha256,
        "status": import_row.status,
        "row_count": import_row.row_count,
        "accepted_count": import_row.accepted_count,
        "duplicate_count": import_row.duplicate_count,
        "error_count": import_row.error_count,
    }
    if extra:
        detail.update(extra)
    await log_event(
        session,
        "bank_feed_import_completed",
        tenant_id=tenant_id,
        detail=detail,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
