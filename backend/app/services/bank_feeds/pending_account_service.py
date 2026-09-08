"""Pending bank accounts — statements uploaded before bank registration.

Also auto-imports into a registered bank when the statement account number
uniquely matches an active bank_accounts.account_number.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_feed import (
    BankAccount,
    BankAccountStatus,
    BankFeedSource,
    PendingBankAccount,
)
from app.services.bank_feeds import account_service, import_service
from app.services.bank_feeds.csv_parser import parse_canonical_bank_csv
from app.services.bank_feeds.fingerprint import file_sha256
from app.services.bank_feeds.pdf_parser import extract_pdf_plain_text, parse_bank_statement_pdf
from app.services.shared.iso4217_catalog import currency_alternation_regex, is_iso4217_currency
from app.services.tenant.tenant_storage_paths import tenant_local_dir
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Require at least this many digits for auto-match (avoid weak last-4 collisions).
_MIN_AUTO_MATCH_DIGITS = 6

_ACCOUNT_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:account\s*(?:no\.?|number|#)?|a/?c\s*(?:no\.?|#)?|acct\.?(?:\s*no\.?)?)"
        r"\s*[:#=\-]?\s*([0-9][0-9\s\-]{4,34}[0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:iban)\s*[:#=\-]?\s*([A-Z]{2}\s*[0-9]{2}[\s0-9A-Z]{10,34})",
        re.IGNORECASE,
    ),
)
_CURRENCY_LABEL_RE = re.compile(
    r"(?:currency|account\s*currency|stmt\s*currency|statement\s*currency)"
    r"\s*[:#=\-]?\s*([A-Za-z]{3})\b",
    re.IGNORECASE,
)
# CSV / metadata style: Account Number,123456789 or Account Number: 123456789
_CSV_META_ACCOUNT_RE = re.compile(
    r"(?im)^[\"']?(?:account\s*(?:no\.?|number|#)?|a/?c\s*(?:no\.?)?)[\"']?\s*[,:=\-]\s*[\"']?"
    r"([0-9][0-9\s\-]{4,34}[0-9])"
)
_ACCOUNT_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?im)^(?:account\s*(?:name|title|holder)|account\s*holder\s*name|"
        r"customer\s*name|client\s*name)\s*[:#=\-]\s*(.+)$"
    ),
    re.compile(
        r"(?:account\s*(?:name|title|holder)|customer\s*name|client\s*name)"
        r"\s*[:#=\-]\s*([^\n\r|,;]{2,80})",
        re.IGNORECASE,
    ),
)
_BANK_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?im)^(?:bank\s*name|financial\s*institution|institution)\s*[:#=\-]\s*(.+)$"
    ),
    re.compile(
        r"(?:bank\s*name|financial\s*institution)\s*[:#=\-]\s*([^\n\r|,;]{2,80})",
        re.IGNORECASE,
    ),
)


@lru_cache(maxsize=1)
def _currency_word_re() -> re.Pattern[str]:
    """Match any ISO 4217 alpha-3 code as a whole word (from pycountry)."""
    return re.compile(rf"\b({currency_alternation_regex()})\b", re.IGNORECASE)


@dataclass
class PendingEnqueueResult:
    pending: PendingBankAccount
    reused_existing: bool
    parse_ok: bool


@dataclass
class PendingPromoteResult:
    pending: PendingBankAccount
    account: BankAccount
    import_result: import_service.ImportResult | None


@dataclass
class UnassignedStatementResult:
    """Outcome of ingesting a statement without an explicit bank account id."""

    disposition: Literal["pending", "auto_imported"]
    pending: PendingBankAccount | None = None
    account: BankAccount | None = None
    import_result: import_service.ImportResult | None = None
    reused_existing: bool = False
    parse_ok: bool = False
    match_reason: str | None = None


def detect_import_source(filename: str | None, content: bytes) -> BankFeedSource:
    name = (filename or "").lower()
    if name.endswith(".pdf") or content.startswith(b"%PDF"):
        return BankFeedSource.PDF
    return BankFeedSource.CSV


def _looks_like_statement_filename(filename: str | None) -> bool:
    name = (filename or "").lower()
    return name.endswith(".pdf") or name.endswith(".csv")


def normalize_account_number_digits(value: str | None) -> str:
    """Digits-only form used for equality matching."""
    return re.sub(r"\D", "", (value or "").strip())


def account_numbers_match(left: str | None, right: str | None) -> bool:
    a = normalize_account_number_digits(left)
    b = normalize_account_number_digits(right)
    if len(a) < _MIN_AUTO_MATCH_DIGITS or len(b) < _MIN_AUTO_MATCH_DIGITS:
        return False
    return a == b


def _statement_text_sample(content: bytes, *, source: BankFeedSource) -> str:
    """Readable statement text for labeled field extraction."""
    try:
        if source == BankFeedSource.PDF:
            text = extract_pdf_plain_text(content)
            if len(text.strip()) >= 40:
                return text
            # Fallback: raw bytes may still contain uncompressed label strings.
            return content[:120_000].decode("latin-1", errors="ignore")
        return content[:120_000].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_account_numbers_from_text(text: str) -> list[str]:
    """Return unique normalized digit strings found via labeled account patterns."""
    return [
        normalize_account_number_digits(raw)
        for raw in extract_account_number_displays(text)
        if normalize_account_number_digits(raw)
    ]


def extract_account_number_displays(text: str) -> list[str]:
    """Return unique account-number displays (preserve dashes/spaces) for user verify."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        cleaned = re.sub(r"\s+", " ", (raw or "").strip())
        digits = normalize_account_number_digits(cleaned)
        if len(digits) < _MIN_AUTO_MATCH_DIGITS:
            return
        if digits in seen:
            return
        seen.add(digits)
        found.append(cleaned)

    for pattern in _ACCOUNT_NUMBER_PATTERNS:
        for m in pattern.finditer(text):
            add(m.group(1))
    for m in _CSV_META_ACCOUNT_RE.finditer(text):
        add(m.group(1))
    return found


def _clean_label_value(raw: str | None) -> str | None:
    if not raw:
        return None
    value = re.sub(r"\s+", " ", raw.strip())
    value = re.split(r"\s{2,}|\t|\|", value)[0].strip(" :#=-\t")
    # Drop values that are clearly account numbers / dates.
    digits = normalize_account_number_digits(value)
    if digits and len(digits) >= _MIN_AUTO_MATCH_DIGITS and len(digits) >= len(value) - 2:
        return None
    if len(value) < 2 or len(value) > 120:
        return None
    return value


def _extract_labeled_name(text: str) -> str | None:
    for pattern in _ACCOUNT_NAME_PATTERNS:
        m = pattern.search(text)
        cleaned = _clean_label_value(m.group(1) if m else None)
        if cleaned:
            return cleaned[:255]
    for pattern in _BANK_NAME_PATTERNS:
        m = pattern.search(text)
        cleaned = _clean_label_value(m.group(1) if m else None)
        if cleaned:
            return cleaned[:255]
    return None


def _extract_currency(text: str) -> str | None:
    labeled = _CURRENCY_LABEL_RE.search(text)
    if labeled:
        code = labeled.group(1).upper()
        if is_iso4217_currency(code):
            return code
    cm = _currency_word_re().search(text)
    return cm.group(1).upper() if cm else None


def _extract_hints(content: bytes, *, source: BankFeedSource, filename: str | None) -> dict[str, Any]:
    text_sample = _statement_text_sample(content, source=source)
    displays = extract_account_number_displays(text_sample)
    numbers = [normalize_account_number_digits(d) for d in displays]
    account_number = displays[0] if displays else None

    currency = _extract_currency(text_sample)
    labeled_name = _extract_labeled_name(text_sample)

    stem = Path(filename or "statement").stem.replace("_", " ").replace("-", " ").strip()
    # Prefer document labels; filename is last-resort placeholder.
    detected_name = labeled_name or (stem[:255] if stem else None)

    return {
        "detected_name": detected_name,
        "detected_account_number": account_number,
        "detected_account_numbers": numbers,
        "detected_currency": currency,
        "text_sample_len": len(text_sample),
        "name_from_document": bool(labeled_name),
    }


def try_parse_statement(
    content: bytes, *, source: BankFeedSource
) -> tuple[bool, int, dict[str, Any] | None]:
    """Return (ok, extracted_count, parse_meta). Fail-open on parser errors."""
    try:
        if source == BankFeedSource.PDF:
            parsed = parse_bank_statement_pdf(content)
        else:
            parsed = parse_canonical_bank_csv(content)
        count = len(parsed.rows)
        meta: dict[str, Any] = {
            "extracted_count": parsed.extracted_count,
            "error_count": len(parsed.errors),
        }
        if getattr(parsed, "parse_meta", None):
            meta["parse_meta"] = parsed.parse_meta
        return count > 0, count, meta
    except Exception as exc:
        return False, 0, {"parse_error": str(exc)[:500]}


def _apply_hints_to_pending(row: PendingBankAccount, hints: dict[str, Any]) -> bool:
    """Fill blank detected_* fields from hints. Returns True when row changed."""
    changed = False
    if not (row.detected_account_number or "").strip() and hints.get("detected_account_number"):
        row.detected_account_number = str(hints["detected_account_number"])[:64]
        changed = True
    if not (row.detected_currency or "").strip() and hints.get("detected_currency"):
        row.detected_currency = str(hints["detected_currency"])[:3].upper()
        changed = True
    name_from_doc = bool(hints.get("name_from_document"))
    hint_name = (hints.get("detected_name") or "").strip()
    if hint_name and (
        not (row.detected_name or "").strip()
        or (name_from_doc and row.detected_name != hint_name)
    ):
        row.detected_name = hint_name[:255]
        changed = True
    meta = dict(row.parse_meta or {}) if isinstance(row.parse_meta, dict) else {}
    if hints.get("detected_account_numbers"):
        meta["detected_account_numbers"] = hints["detected_account_numbers"]
        meta["name_from_document"] = name_from_doc
        row.parse_meta = meta
        changed = True
    return changed


def refresh_pending_hints_from_stored_file(row: PendingBankAccount) -> bool:
    """Re-extract verify fields from the stored statement when detections are incomplete."""
    needs = (
        not (row.detected_account_number or "").strip()
        or not (row.detected_currency or "").strip()
        or not (row.detected_name or "").strip()
    )
    if not needs:
        return False
    path = Path(row.stored_path) if row.stored_path else None
    if path is None or not path.is_file():
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    source = BankFeedSource(row.source) if row.source else detect_import_source(row.filename, content)
    hints = _extract_hints(content, source=source, filename=row.filename)
    return _apply_hints_to_pending(row, hints)


def _store_pending_file(
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    filename: str | None,
    digest: str,
) -> str:
    folder = tenant_local_dir(tenant_id, "bank_feeds", "pending")
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename or "statement.bin").suffix or ".bin"
    safe_stem = re.sub(r"[^\w.\-]+", "_", Path(filename or "statement").stem)[:80] or "statement"
    dest = folder / f"{safe_stem}_{digest[:12]}_{time.time_ns() // 1_000_000}{suffix}"
    dest.write_bytes(content)
    return str(dest)


async def list_pending_bank_accounts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[PendingBankAccount]:
    stmt = (
        select(PendingBankAccount)
        .where(
            PendingBankAccount.tenant_id == tenant_id,
            PendingBankAccount.status == "pending",
        )
        .order_by(PendingBankAccount.created_at.desc(), PendingBankAccount.id.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    refreshed = False
    for row in rows:
        if refresh_pending_hints_from_stored_file(row):
            refreshed = True
    if refreshed:
        await session.flush()
    return rows


async def get_pending_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pending_id: int,
) -> PendingBankAccount | None:
    stmt = select(PendingBankAccount).where(
        PendingBankAccount.tenant_id == tenant_id,
        PendingBankAccount.id == pending_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_unique_matching_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_numbers: list[str],
    detected_currency: str | None = None,
) -> tuple[BankAccount | None, str | None]:
    """Return (account, reason) when exactly one active bank matches.

    Matching rules (conservative):
    - Digits-only equality, each side >= 6 digits
    - If statement currency is present and differs from the bank's currency → reject that candidate
    - 0 matches or >1 matches → no auto-import (caller queues Pending)
    """
    if not candidate_numbers:
        return None, None

    accounts = await account_service.list_bank_accounts(
        session, tenant_id=tenant_id, include_archived=False
    )
    active = [a for a in accounts if a.status == BankAccountStatus.ACTIVE.value]

    matches: list[BankAccount] = []
    for account in active:
        registered = normalize_account_number_digits(account.account_number)
        if len(registered) < _MIN_AUTO_MATCH_DIGITS:
            continue
        for cand in candidate_numbers:
            if not account_numbers_match(cand, registered):
                continue
            if (
                detected_currency
                and account.currency
                and detected_currency.upper() != account.currency.upper()
            ):
                # Currency conflict — skip this candidate for auto-match.
                continue
            matches.append(account)
            break

    # De-dupe by id if multiple candidate numbers hit the same account.
    unique_by_id: dict[int, BankAccount] = {a.id: a for a in matches}
    unique = list(unique_by_id.values())
    if len(unique) == 1:
        return unique[0], "account_number_exact"
    if len(unique) > 1:
        return None, "ambiguous_account_number"
    return None, None


async def enqueue_pending_bank_statement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    filename: str | None,
    require_parse_success: bool = False,
    hints: dict[str, Any] | None = None,
    parse_ok: bool | None = None,
    extracted_count: int | None = None,
    parse_meta: dict[str, Any] | None = None,
    source: BankFeedSource | None = None,
) -> PendingEnqueueResult | None:
    """Store statement and create pending row. Returns None when require_parse_success and parse fails."""
    if not content:
        return None
    source = source or detect_import_source(filename, content)
    if parse_ok is None or extracted_count is None:
        parse_ok, extracted_count, parse_meta = try_parse_statement(content, source=source)
    if require_parse_success and not parse_ok:
        return None

    digest = file_sha256(content)
    existing = (
        await session.execute(
            select(PendingBankAccount).where(
                PendingBankAccount.tenant_id == tenant_id,
                PendingBankAccount.file_sha256 == digest,
                PendingBankAccount.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return PendingEnqueueResult(pending=existing, reused_existing=True, parse_ok=bool(parse_ok))

    hints = hints or _extract_hints(content, source=source, filename=filename)
    stored_path = _store_pending_file(
        tenant_id=tenant_id,
        content=content,
        filename=filename,
        digest=digest,
    )
    confidence = 80.0 if parse_ok else 40.0
    meta = dict(parse_meta or {})
    if hints.get("detected_account_numbers"):
        meta["detected_account_numbers"] = hints["detected_account_numbers"]
    if hints.get("name_from_document") is not None:
        meta["name_from_document"] = hints["name_from_document"]
    row = PendingBankAccount(
        tenant_id=tenant_id,
        detected_name=hints.get("detected_name"),
        detected_account_number=hints.get("detected_account_number"),
        detected_currency=hints.get("detected_currency"),
        filename=filename,
        file_sha256=digest,
        source=source.value,
        stored_path=stored_path,
        extracted_count=int(extracted_count or 0),
        confidence=confidence,
        parse_meta=meta or None,
        status="pending",
    )
    session.add(row)
    await session.flush()
    return PendingEnqueueResult(pending=row, reused_existing=False, parse_ok=bool(parse_ok))


async def ingest_unassigned_bank_statement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    filename: str | None,
    require_parse_success: bool = False,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> UnassignedStatementResult | None:
    """Auto-import when account number uniquely matches a registered bank; else Pending."""
    if not content:
        return None

    source = detect_import_source(filename, content)
    parse_ok, extracted_count, parse_meta = try_parse_statement(content, source=source)
    if require_parse_success and not parse_ok:
        return None

    hints = _extract_hints(content, source=source, filename=filename)
    candidates: list[str] = list(hints.get("detected_account_numbers") or [])
    if hints.get("detected_account_number") and hints["detected_account_number"] not in candidates:
        candidates.insert(0, hints["detected_account_number"])

    matched, match_reason = await find_unique_matching_bank_account(
        session,
        tenant_id=tenant_id,
        candidate_numbers=candidates,
        detected_currency=hints.get("detected_currency"),
    )

    if matched is not None and match_reason == "account_number_exact":
        import_result = await import_service.import_statement(
            session,
            tenant_id=tenant_id,
            account=matched,
            content=content,
            filename=filename,
            source=source,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
        logger.info(
            "bank_statement_auto_imported",
            tenant_id=str(tenant_id),
            bank_account_id=matched.id,
            filename=filename,
            match_reason=match_reason,
            accepted_count=import_result.import_row.accepted_count,
        )
        return UnassignedStatementResult(
            disposition="auto_imported",
            account=matched,
            import_result=import_result,
            reused_existing=import_result.reused_existing,
            parse_ok=parse_ok,
            match_reason=match_reason,
        )

    # Ambiguous or no match → Pending registration queue.
    pending = await enqueue_pending_bank_statement(
        session,
        tenant_id=tenant_id,
        content=content,
        filename=filename,
        require_parse_success=require_parse_success,
        hints=hints,
        parse_ok=parse_ok,
        extracted_count=extracted_count,
        parse_meta=parse_meta,
        source=source,
    )
    if pending is None:
        return None
    reason = match_reason or ("no_account_number" if not candidates else "no_registered_match")
    return UnassignedStatementResult(
        disposition="pending",
        pending=pending.pending,
        reused_existing=pending.reused_existing,
        parse_ok=pending.parse_ok,
        match_reason=reason,
    )


async def try_divert_email_attachment_to_pending(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content: bytes,
    filename: str | None,
) -> UnassignedStatementResult | None:
    """If content parses as a bank statement, auto-import or enqueue pending."""
    if not _looks_like_statement_filename(filename) and not (content.startswith(b"%PDF")):
        name = (filename or "").lower()
        if not name.endswith(".csv"):
            return None
    return await ingest_unassigned_bank_statement(
        session,
        tenant_id=tenant_id,
        content=content,
        filename=filename,
        require_parse_success=True,
    )


async def dismiss_pending_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pending_id: int,
) -> PendingBankAccount | None:
    row = await get_pending_bank_account(session, tenant_id=tenant_id, pending_id=pending_id)
    if row is None or row.status != "pending":
        return None
    row.status = "dismissed"
    row.resolved_at = datetime.now(UTC)
    await session.flush()
    return row


async def promote_pending_bank_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pending_id: int,
    name: str,
    account_number: str,
    currency: str,
    coa_account_name: str,
    bank_account_id: int | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> PendingPromoteResult:
    row = await get_pending_bank_account(session, tenant_id=tenant_id, pending_id=pending_id)
    if row is None or row.status != "pending":
        raise ValueError("Pending bank account not found")

    if bank_account_id is not None:
        account = await account_service.get_bank_account(
            session, tenant_id=tenant_id, account_id=bank_account_id
        )
        if account is None:
            raise ValueError("Bank account not found")
    else:
        account = await account_service.create_bank_account(
            session,
            tenant_id=tenant_id,
            name=name,
            currency=currency,
            account_number=account_number,
            coa_account_name=coa_account_name,
        )

    content = Path(row.stored_path).read_bytes()
    source = (
        BankFeedSource(row.source)
        if row.source in {s.value for s in BankFeedSource}
        else detect_import_source(row.filename, content)
    )
    import_result = await import_service.import_statement(
        session,
        tenant_id=tenant_id,
        account=account,
        content=content,
        filename=row.filename,
        source=source,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )

    row.status = "promoted"
    row.promoted_bank_account_id = account.id
    row.resolved_at = datetime.now(UTC)
    await session.flush()
    return PendingPromoteResult(pending=row, account=account, import_result=import_result)
