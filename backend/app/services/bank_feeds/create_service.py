"""Post (and reverse) a bank-create journal for an unmatched bank line."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.jurisdiction.packs import tenant_jurisdiction
from app.models.bank_feed import (
    BankAccount,
    BankTransaction,
    BankTxnDirection,
    BankTxnMatchStatus,
)
from app.models.customer import CustomerRegistry
from app.models.journal import EntryType, JournalEntryKind
from app.models.journal_batch import JournalBatch
from app.models.tenant import Tenant
from app.models.vendor import VendorRegistry
from app.schemas.customer import CustomerCreate
from app.schemas.vendor import VendorCreate
from app.services.audit.audit_service import log_event
from app.services.master_data.customer_registry_service import create_customer_registry
from app.services.master_data.vendor_registry_service import create_vendor_registry
from app.services.master_data.vendor_resolver import slugify_vendor_name
from app.services.payments.journal_fx import round_money
from app.services.payments.journal_generator import JournalLine
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.payments.journal_reversal_service import reverse_batch
from app.services.rule_book.account_mapper import resolve_category_for_config
from app.services.rule_book.rule_book_mapper import (
    get_tax_account_mapping,
    load_classification_config,
)

PartyType = Literal["vendor", "customer"]

_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")
_CENT = Decimal("0.01")


class BankCreateConflict(Exception):
    """Create or reverse lost the atomic claim (already posted / already reversed)."""


class BankCreateError(ValueError):
    """Caller-facing validation error for bank create / reverse."""


@dataclass(frozen=True)
class BankCreatePartyInput:
    name: str


def inclusive_tax_split(gross: Decimal, rate_percent: Decimal) -> tuple[Decimal, Decimal]:
    """Split a tax-inclusive bank amount into (net, tax).

    gst = round(gross - gross / (1 + rate/100)); net = gross - gst.
    """
    gross = round_money(gross.copy_abs())
    rate = Decimal(str(rate_percent))
    if rate <= 0:
        return gross, _ZERO
    divisor = Decimal("1") + (rate / _HUNDRED)
    tax = (gross - (gross / divisor)).quantize(_CENT, rounding=ROUND_HALF_UP)
    net = round_money(gross - tax)
    return net, tax


def _quantized_rate(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def claim_bank_create_slot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    transaction_id: int,
) -> bool:
    """Atomically take the unmatched line for posting. True iff this caller won."""
    result = await session.execute(
        update(BankTransaction)
        .where(
            BankTransaction.id == transaction_id,
            BankTransaction.tenant_id == tenant_id,
            BankTransaction.match_status == BankTxnMatchStatus.UNMATCHED.value,
            BankTransaction.posted_journal_batch_id.is_(None),
        )
        .values(match_status=BankTxnMatchStatus.POSTED.value)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


async def claim_bank_reverse_slot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    transaction_id: int,
    posted_journal_batch_id: int,
) -> bool:
    """Atomically release a posted line. True iff this caller won."""
    result = await session.execute(
        update(BankTransaction)
        .where(
            BankTransaction.id == transaction_id,
            BankTransaction.tenant_id == tenant_id,
            BankTransaction.match_status == BankTxnMatchStatus.POSTED.value,
            BankTransaction.posted_journal_batch_id == posted_journal_batch_id,
        )
        .values(
            match_status=BankTxnMatchStatus.UNMATCHED.value,
            posted_journal_batch_id=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount == 1


async def _unique_party_slug(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    base: str,
    party_type: PartyType,
) -> str:
    slug = (base or "bank-party")[:100]
    n = 2
    while True:
        if party_type == "vendor":
            exists = (
                await session.execute(
                    select(VendorRegistry.id).where(
                        VendorRegistry.tenant_id == tenant_id,
                        VendorRegistry.vendor_slug == slug,
                    )
                )
            ).scalar_one_or_none()
        else:
            exists = (
                await session.execute(
                    select(CustomerRegistry.id).where(
                        CustomerRegistry.tenant_id == tenant_id,
                        CustomerRegistry.customer_slug == slug,
                    )
                )
            ).scalar_one_or_none()
        if exists is None:
            return slug
        suffix = f"-{n}"
        slug = (base[: max(1, 100 - len(suffix))] + suffix)[:100]
        n += 1


async def _resolve_or_create_party(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    party_type: PartyType,
    party_id: int | None,
    create_party: BankCreatePartyInput | None,
) -> tuple[int | None, int | None, str]:
    if (party_id is None) == (create_party is None):
        raise BankCreateError("Provide exactly one of party_id or create_party")

    if create_party is not None:
        name = create_party.name.strip()
        if not name:
            raise BankCreateError("Contact name is required")
        base_slug = slugify_vendor_name(name) or "bank-party"
        slug = await _unique_party_slug(
            session, tenant_id=tenant_id, base=base_slug, party_type=party_type
        )
        pattern = f"bank:{slug}"[:255]
        if party_type == "vendor":
            row = await create_vendor_registry(
                session,
                tenant_id=tenant_id,
                body=VendorCreate(
                    vendor_slug=slug,
                    vendor_name=name,
                    sender_pattern=pattern,
                    approved=True,
                ),
            )
            return row.id, None, row.vendor_name
        row = await create_customer_registry(
            session,
            tenant_id=tenant_id,
            body=CustomerCreate(
                customer_slug=slug,
                customer_name=name,
                sender_pattern=pattern,
                approved=True,
            ),
        )
        return None, row.id, row.customer_name

    assert party_id is not None
    if party_type == "vendor":
        vendor = (
            await session.execute(
                select(VendorRegistry).where(
                    VendorRegistry.tenant_id == tenant_id,
                    VendorRegistry.id == party_id,
                )
            )
        ).scalar_one_or_none()
        if vendor is None:
            raise BankCreateError("Vendor not found")
        return vendor.id, None, vendor.vendor_name
    customer = (
        await session.execute(
            select(CustomerRegistry).where(
                CustomerRegistry.tenant_id == tenant_id,
                CustomerRegistry.id == party_id,
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise BankCreateError("Customer not found")
    return None, customer.id, customer.customer_name


def _build_lines(
    *,
    txn: BankTransaction,
    account: BankAccount,
    ledger_code: str,
    ledger_name: str,
    tax_code: str,
    tax_name: str,
    net: Decimal,
    tax: Decimal,
    vendor_id: int | None,
    customer_id: int | None,
    txn_currency: str,
    base_currency: str,
) -> list[JournalLine]:
    gross = round_money(Decimal(str(txn.amount)).copy_abs())
    on = txn.txn_date
    bank_line = JournalLine(
        date=on,
        account_code=account.coa_account_code[:20],
        account_name=account.coa_account_name[:255],
        debit=_ZERO,
        credit=_ZERO,
        entry_type=EntryType.CREDIT,
        txn_currency=txn_currency,
        base_currency=base_currency,
    )
    pnl = JournalLine(
        date=on,
        account_code=ledger_code[:20],
        account_name=ledger_name[:255],
        debit=_ZERO,
        credit=_ZERO,
        entry_type=EntryType.DEBIT,
        vendor_registry_id=vendor_id,
        customer_registry_id=customer_id,
        txn_currency=txn_currency,
        base_currency=base_currency,
    )
    tax_line: JournalLine | None = None
    if tax > 0:
        tax_line = JournalLine(
            date=on,
            account_code=tax_code[:20],
            account_name=tax_name[:255],
            debit=_ZERO,
            credit=_ZERO,
            entry_type=EntryType.DEBIT,
            vendor_registry_id=vendor_id,
            customer_registry_id=customer_id,
            txn_currency=txn_currency,
            base_currency=base_currency,
        )

    money_out = txn.direction == BankTxnDirection.DEBIT.value
    if money_out:
        pnl.debit = net
        pnl.credit = _ZERO
        pnl.entry_type = EntryType.DEBIT
        bank_line.debit = _ZERO
        bank_line.credit = gross
        bank_line.entry_type = EntryType.CREDIT
        if tax_line is not None:
            tax_line.debit = tax
            tax_line.credit = _ZERO
            tax_line.entry_type = EntryType.DEBIT
    else:
        bank_line.debit = gross
        bank_line.credit = _ZERO
        bank_line.entry_type = EntryType.DEBIT
        pnl.debit = _ZERO
        pnl.credit = net
        pnl.entry_type = EntryType.CREDIT
        if tax_line is not None:
            tax_line.debit = _ZERO
            tax_line.credit = tax
            tax_line.entry_type = EntryType.CREDIT

    lines = [pnl]
    if tax_line is not None:
        lines.append(tax_line)
    lines.append(bank_line)
    return lines


async def create_bank_journal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    account: BankAccount,
    party_type: PartyType,
    party_id: int | None,
    create_party: BankCreatePartyInput | None,
    ledger: str,
    description: str,
    tax_rate_percent: float | Decimal,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    money_out = txn.direction == BankTxnDirection.DEBIT.value
    expected: PartyType = "vendor" if money_out else "customer"
    if party_type != expected:
        raise BankCreateError(
            "Money-out lines require a vendor; money-in lines require a customer"
        )

    desc = description.strip()
    if not desc:
        raise BankCreateError("Description is required")
    ledger_name = ledger.strip()
    if not ledger_name:
        raise BankCreateError("Ledger is required")

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise BankCreateError("Tenant not found")
    pack = tenant_jurisdiction(tenant)
    requested = _quantized_rate(tax_rate_percent)
    statutory = (
        pack.statutory_tax_rate.quantize(Decimal("0.01"))
        if pack.statutory_tax_rate is not None
        else None
    )
    allowed = {_ZERO}
    if statutory is not None:
        allowed.add(statutory)
    if requested not in allowed:
        raise BankCreateError(
            "tax_rate_percent must be 0 or the jurisdiction statutory rate"
        )

    vendor_id, customer_id, party_name = await _resolve_or_create_party(
        session,
        tenant_id=tenant_id,
        party_type=party_type,
        party_id=party_id,
        create_party=create_party,
    )

    won = await claim_bank_create_slot(
        session, tenant_id=tenant_id, transaction_id=txn.id
    )
    if not won:
        raise BankCreateConflict("This bank line already has a journal")

    config = await load_classification_config(session, tenant_id)
    mapping = resolve_category_for_config(ledger_name, config)
    if money_out:
        tax_map = get_tax_account_mapping(config)
    else:
        sales_tax_label = pack.posting_defaults.sales_tax_account or "Tax Collected"
        tax_map = resolve_category_for_config(sales_tax_label, config)

    net, tax = inclusive_tax_split(Decimal(str(txn.amount)), requested)
    txn_currency = (txn.currency or "").strip().upper() or tenant.currency
    base_currency = (tenant.currency or "").strip().upper()
    lines = _build_lines(
        txn=txn,
        account=account,
        ledger_code=mapping.account_code,
        ledger_name=mapping.account_name,
        tax_code=tax_map.account_code,
        tax_name=tax_map.account_name,
        net=net,
        tax=tax,
        vendor_id=vendor_id,
        customer_id=customer_id,
        txn_currency=txn_currency,
        base_currency=base_currency,
    )
    batch = await persist_journal_lines(
        session,
        None,
        lines,
        entry_kind=JournalEntryKind.BANK_CREATE,
        tenant_id=tenant_id,
        base_currency=base_currency,
    )
    await session.flush()

    attach = await session.execute(
        update(BankTransaction)
        .where(
            BankTransaction.id == txn.id,
            BankTransaction.tenant_id == tenant_id,
            BankTransaction.match_status == BankTxnMatchStatus.POSTED.value,
            BankTransaction.posted_journal_batch_id.is_(None),
        )
        .values(posted_journal_batch_id=batch.id)
        .execution_options(synchronize_session="fetch")
    )
    if attach.rowcount != 1:
        raise BankCreateConflict("This bank line already has a journal")

    flags = dict(txn.review_flags) if isinstance(txn.review_flags, dict) else {}
    flags["create_posting"] = {
        "description": desc,
        "ledger": mapping.account_name,
        "tax_rate_percent": float(requested),
        "party_type": party_type,
        "party_id": vendor_id or customer_id,
        "party_name": party_name,
        "journal_batch_id": batch.id,
    }
    txn.review_flags = flags
    txn.category_coa = mapping.account_name
    await session.flush()

    await log_event(
        session,
        "bank_txn_create_posted",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "journal_batch_id": batch.id,
            "party_type": party_type,
            "party_id": vendor_id or customer_id,
            "party_name": party_name,
            "account": mapping.account_name,
            "tax_rate_percent": float(requested),
            "amount": str(round_money(Decimal(str(txn.amount)).copy_abs())),
            "description": desc,
            "actor_user": actor_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await session.refresh(txn)
    return txn


async def reverse_bank_journal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    txn: BankTransaction,
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None = None,
) -> BankTransaction:
    batch_id = txn.posted_journal_batch_id
    if (
        txn.match_status != BankTxnMatchStatus.POSTED.value
        or batch_id is None
    ):
        raise BankCreateError("This bank line is not posted")

    won = await claim_bank_reverse_slot(
        session,
        tenant_id=tenant_id,
        transaction_id=txn.id,
        posted_journal_batch_id=batch_id,
    )
    if not won:
        raise BankCreateConflict("This posting has already been reversed")

    batch = await session.get(JournalBatch, batch_id)
    if batch is None or batch.tenant_id != tenant_id:
        raise BankCreateError("Posted journal was not found")
    reversal = await reverse_batch(
        session, batch, reason="bank_create_reverse"
    )

    flags = dict(txn.review_flags) if isinstance(txn.review_flags, dict) else {}
    posting = flags.get("create_posting")
    reversal_id = reversal.id if reversal is not None else None
    if isinstance(posting, dict):
        flags["create_posting"] = {**posting, "reversed_by_batch_id": reversal_id}
        txn.review_flags = flags
    await session.flush()

    await log_event(
        session,
        "bank_txn_create_reversed",
        tenant_id=tenant_id,
        detail={
            "bank_transaction_id": txn.id,
            "journal_batch_id": batch_id,
            "reversal_batch_id": reversal_id,
            "actor_user": actor_name,
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await session.refresh(txn)
    return txn
