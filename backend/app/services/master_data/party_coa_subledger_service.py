"""Create and resolve party COA sub-ledgers under Rule Book AP/AR control parents."""

from __future__ import annotations

import re
import uuid
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rule_book_config import (
    ChartOfAccountEntry,
    RuleBookConfigPayload,
    SubLedgerEntry,
    validate_rule_book_config_payload,
)
from app.services.rule_book.account_mapper import AccountMapping, clear_rule_book_cache
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config
from app.services.rule_book.rule_book_mapper import (
    get_payable_account_mapping,
    get_receivable_account_mapping,
)

logger = structlog.get_logger(__name__)

PartyKind = Literal["vendor", "customer"]

# journal_entries.account_code is String(20)
_PARTY_CODE_MAX = 20


def party_sub_ledger_code(slug: str) -> str:
    """Stable COA sub-ledger code from registry slug (journal-safe length)."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (slug or "").strip().upper()).strip("-")
    if not cleaned:
        cleaned = "PARTY"
    code = cleaned[:_PARTY_CODE_MAX].rstrip("-")
    return code or "PARTY"


def find_coa_entry_by_name(
    entries: list[ChartOfAccountEntry],
    ledger_name: str,
) -> ChartOfAccountEntry | None:
    cleaned = (ledger_name or "").strip()
    if not cleaned:
        return None
    for entry in entries:
        if entry.name.strip() == cleaned:
            return entry
    lowered = cleaned.lower()
    for entry in entries:
        if entry.name.strip().lower() == lowered:
            return entry
    return None


def control_account_codes_for_parent(
    config: RuleBookConfigPayload,
    parent: AccountMapping,
) -> list[str]:
    """Parent account code plus all nested sub-ledger codes (party + manual)."""
    codes: list[str] = []
    parent_code = (parent.account_code or "").strip()
    if parent_code:
        codes.append(parent_code)
    entry = find_coa_entry_by_name(config.chart_of_accounts, parent.account_name)
    if entry is None:
        return codes
    for sub in entry.sub_ledgers:
        code = (sub.code or "").strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def resolve_party_child_mapping(
    config: RuleBookConfigPayload,
    *,
    parent_ledger_name: str,
    slug: str,
) -> AccountMapping | None:
    """Return party child mapping when a sub-ledger with the slug-derived code exists."""
    parent_entry = find_coa_entry_by_name(config.chart_of_accounts, parent_ledger_name)
    if parent_entry is None:
        return None
    code = party_sub_ledger_code(slug)
    code_upper = code.upper()
    for sub in parent_entry.sub_ledgers:
        if sub.code.strip().upper() == code_upper:
            return AccountMapping(
                account_code=sub.code.strip(),
                account_name=sub.name.strip(),
                expense_category=sub.name.strip(),
            )
    return None


def _upsert_sub_ledger_on_parent(
    parent: ChartOfAccountEntry,
    *,
    slug: str,
    party_name: str,
) -> SubLedgerEntry:
    code = party_sub_ledger_code(slug)
    name = (party_name or "").strip() or code
    code_upper = code.upper()
    for idx, sub in enumerate(parent.sub_ledgers):
        if sub.code.strip().upper() == code_upper:
            updated = SubLedgerEntry(code=sub.code.strip(), name=name, origin="party")
            parent.sub_ledgers[idx] = updated
            return updated
    # Avoid name collisions with a different code under the same parent.
    name_lower = name.lower()
    for sub in parent.sub_ledgers:
        if sub.name.strip().lower() == name_lower and sub.code.strip().upper() != code_upper:
            name = f"{name} ({code})"
            break
    created = SubLedgerEntry(code=code, name=name, origin="party")
    parent.sub_ledgers.append(created)
    return created


async def upsert_party_coa_sub_ledger(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    parent_ledger_name: str,
    slug: str,
    party_name: str,
    updated_by_user_id: int | None = None,
) -> AccountMapping | None:
    """
    Idempotently create/update a party COA child under the Rule Book–selected parent.

    Returns the child AccountMapping, or None when the parent ledger is missing from COA.
    """
    parent_label = (parent_ledger_name or "").strip()
    cleaned_slug = (slug or "").strip()
    if not parent_label or not cleaned_slug:
        return None

    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    parent = find_coa_entry_by_name(payload.chart_of_accounts, parent_label)
    if parent is None:
        logger.warning(
            "party_coa_parent_missing",
            tenant_id=str(tenant_id),
            parent_ledger=parent_label,
            slug=cleaned_slug,
        )
        return None

    child = _upsert_sub_ledger_on_parent(
        parent,
        slug=cleaned_slug,
        party_name=party_name,
    )
    await save_rule_book_config(
        session,
        payload,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
    clear_rule_book_cache()
    return AccountMapping(
        account_code=child.code,
        account_name=child.name,
        expense_category=child.name,
    )


async def ensure_vendor_party_coa_sub_ledger(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    slug: str,
    vendor_name: str,
    config: RuleBookConfigPayload | None = None,
    updated_by_user_id: int | None = None,
) -> AccountMapping | None:
    """Ensure vendor party child under Posting defaults → Payable account."""
    if config is None:
        raw = await load_rule_book_config_dict(session, tenant_id)
        config = validate_rule_book_config_payload(raw)
    parent_name = (config.posting_defaults.payable_account or "").strip()
    existing = resolve_party_child_mapping(
        config, parent_ledger_name=parent_name, slug=slug
    )
    if existing is not None:
        # Refresh name if registry renamed.
        if existing.account_name.strip() != (vendor_name or "").strip():
            return await upsert_party_coa_sub_ledger(
                session,
                tenant_id,
                parent_ledger_name=parent_name,
                slug=slug,
                party_name=vendor_name,
                updated_by_user_id=updated_by_user_id,
            )
        return existing
    return await upsert_party_coa_sub_ledger(
        session,
        tenant_id,
        parent_ledger_name=parent_name,
        slug=slug,
        party_name=vendor_name,
        updated_by_user_id=updated_by_user_id,
    )


async def ensure_customer_party_coa_sub_ledger(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    slug: str,
    customer_name: str,
    config: RuleBookConfigPayload | None = None,
    updated_by_user_id: int | None = None,
) -> AccountMapping | None:
    """Ensure customer party child under Posting defaults → Receivable account."""
    if config is None:
        raw = await load_rule_book_config_dict(session, tenant_id)
        config = validate_rule_book_config_payload(raw)
    parent_name = (config.posting_defaults.receivable_account or "").strip()
    existing = resolve_party_child_mapping(
        config, parent_ledger_name=parent_name, slug=slug
    )
    if existing is not None:
        if existing.account_name.strip() != (customer_name or "").strip():
            return await upsert_party_coa_sub_ledger(
                session,
                tenant_id,
                parent_ledger_name=parent_name,
                slug=slug,
                party_name=customer_name,
                updated_by_user_id=updated_by_user_id,
            )
        return existing
    return await upsert_party_coa_sub_ledger(
        session,
        tenant_id,
        parent_ledger_name=parent_name,
        slug=slug,
        party_name=customer_name,
        updated_by_user_id=updated_by_user_id,
    )


def employee_advance_parent_ledger(
    config: RuleBookConfigPayload,
    *,
    employee_parent_ledger: str | None = None,
) -> str:
    """Employee-selected advance parent, else the Team Expenses org default."""
    chosen = (employee_parent_ledger or "").strip()
    if chosen:
        return chosen
    return (config.team_expense_posting.default_advance_parent_ledger or "").strip()


async def ensure_employee_party_coa_sub_ledger(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    slug: str,
    employee_name: str,
    parent_ledger_name: str | None = None,
    config: RuleBookConfigPayload | None = None,
    updated_by_user_id: int | None = None,
) -> AccountMapping | None:
    """Ensure the employee advance child under the parent chosen on the employee master."""
    if config is None:
        raw = await load_rule_book_config_dict(session, tenant_id)
        config = validate_rule_book_config_payload(raw)
    parent_name = employee_advance_parent_ledger(
        config,
        employee_parent_ledger=parent_ledger_name,
    )
    if not parent_name:
        return None
    existing = resolve_party_child_mapping(
        config, parent_ledger_name=parent_name, slug=slug
    )
    if existing is not None and existing.account_name.strip() == (employee_name or "").strip():
        return existing
    return await upsert_party_coa_sub_ledger(
        session,
        tenant_id,
        parent_ledger_name=parent_name,
        slug=slug,
        party_name=employee_name,
        updated_by_user_id=updated_by_user_id,
    )


async def resolve_employee_advance_mapping(
    session: AsyncSession,
    invoice,
    config: RuleBookConfigPayload,
) -> AccountMapping:
    """
    Resolve the employee advance control line for Team Expenses journals.

    Falls back to the org default advance parent when the sender is not a known employee.
    """
    from app.services.rule_book.account_mapper import resolve_category_for_config
    from app.services.purchase.team_expense_validator import resolve_employee_for_sender

    parent_fallback = resolve_category_for_config(
        employee_advance_parent_ledger(config),
        config,
    )
    employee = await resolve_employee_for_sender(
        session,
        invoice.tenant_id,
        invoice.email_sender,
    )
    if employee is None:
        return parent_fallback

    child = await ensure_employee_party_coa_sub_ledger(
        session,
        invoice.tenant_id,
        slug=employee.id,
        employee_name=employee.name,
        parent_ledger_name=getattr(employee, "advance_parent_ledger", "") or "",
        config=config,
    )
    return child or parent_fallback


async def resolve_party_control_mapping_for_journal(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    *,
    kind: PartyKind,
    slug: str | None,
    party_name: str | None,
) -> AccountMapping:
    """
    Resolve AP/AR control line mapping: party COA child when possible, else parent.

    Creates the party child on post when slug is known (create-on-post fallback).
    """
    parent = (
        get_payable_account_mapping(config)
        if kind == "vendor"
        else get_receivable_account_mapping(config)
    )
    cleaned_slug = (slug or "").strip()
    if not cleaned_slug:
        return parent

    name = (party_name or "").strip() or cleaned_slug
    if kind == "vendor":
        child = await ensure_vendor_party_coa_sub_ledger(
            session,
            tenant_id,
            slug=cleaned_slug,
            vendor_name=name,
            config=config,
        )
    else:
        child = await ensure_customer_party_coa_sub_ledger(
            session,
            tenant_id,
            slug=cleaned_slug,
            customer_name=name,
            config=config,
        )
    return child or parent


def parent_control_mapping_fallback(
    config: RuleBookConfigPayload,
    *,
    kind: PartyKind,
) -> AccountMapping:
    if kind == "vendor":
        return get_payable_account_mapping(config)
    return get_receivable_account_mapping(config)


def sync_party_control_mapping_from_config(
    config: RuleBookConfigPayload,
    *,
    kind: PartyKind,
    slug: str | None,
) -> AccountMapping:
    """Sync lookup of existing party child; falls back to parent (no COA write)."""
    parent = parent_control_mapping_fallback(config, kind=kind)
    cleaned_slug = (slug or "").strip()
    if not cleaned_slug:
        return parent
    child = resolve_party_child_mapping(
        config,
        parent_ledger_name=parent.account_name,
        slug=cleaned_slug,
    )
    return child or parent


async def resolve_invoice_control_mapping(
    session: AsyncSession,
    invoice,
    config: RuleBookConfigPayload,
    *,
    vendor_registry_id: int | None,
    customer_registry_id: int | None,
) -> AccountMapping:
    """Resolve AP/AR control mapping for accrual journals (party child when registered)."""
    from app.models.customer import CustomerRegistry
    from app.models.vendor import VendorRegistry
    from app.services.rule_book.rule_book_mapper import ROUTE_SALES, ROUTE_TEAM

    if (invoice.route_target or "").strip() == ROUTE_TEAM:
        return await resolve_employee_advance_mapping(session, invoice, config)

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        if customer_registry_id is not None:
            row = await session.get(CustomerRegistry, customer_registry_id)
            if row is not None and row.tenant_id == invoice.tenant_id:
                return await resolve_party_control_mapping_for_journal(
                    session,
                    invoice.tenant_id,
                    config,
                    kind="customer",
                    slug=row.customer_slug,
                    party_name=row.customer_name,
                )
        return get_receivable_account_mapping(config)

    if vendor_registry_id is not None:
        row = await session.get(VendorRegistry, vendor_registry_id)
        if row is not None and row.tenant_id == invoice.tenant_id:
            return await resolve_party_control_mapping_for_journal(
                session,
                invoice.tenant_id,
                config,
                kind="vendor",
                slug=row.vendor_slug,
                party_name=row.vendor_name,
            )
    return get_payable_account_mapping(config)


async def resolve_settlement_control_context(
    session: AsyncSession,
    invoice,
    config: RuleBookConfigPayload,
    *,
    kind: PartyKind,
    registry_id: int | None,
) -> tuple[AccountMapping, int | None]:
    """
    Resolve settlement control mapping + registry id.

    Falls back to the invoice accrual control line when payment/collection lacks a registry id.
    """
    from sqlalchemy import select

    from app.models.customer import CustomerRegistry
    from app.models.journal import JournalEntry, JournalEntryKind
    from app.models.vendor import VendorRegistry

    resolved_id = registry_id
    if resolved_id is None:
        id_col = (
            JournalEntry.vendor_registry_id
            if kind == "vendor"
            else JournalEntry.customer_registry_id
        )
        stmt = (
            select(id_col)
            .where(
                JournalEntry.tenant_id == invoice.tenant_id,
                JournalEntry.invoice_id == invoice.id,
                JournalEntry.entry_kind == JournalEntryKind.INVOICE_ACCRUAL,
                id_col.is_not(None),
            )
            .limit(1)
        )
        resolved_id = (await session.execute(stmt)).scalar_one_or_none()

    if resolved_id is not None:
        if kind == "vendor":
            row = await session.get(VendorRegistry, resolved_id)
            if row is not None and row.tenant_id == invoice.tenant_id:
                mapping = await resolve_party_control_mapping_for_journal(
                    session,
                    invoice.tenant_id,
                    config,
                    kind="vendor",
                    slug=row.vendor_slug,
                    party_name=row.vendor_name,
                )
                return mapping, resolved_id
        else:
            row = await session.get(CustomerRegistry, resolved_id)
            if row is not None and row.tenant_id == invoice.tenant_id:
                mapping = await resolve_party_control_mapping_for_journal(
                    session,
                    invoice.tenant_id,
                    config,
                    kind="customer",
                    slug=row.customer_slug,
                    party_name=row.customer_name,
                )
                return mapping, resolved_id

    return parent_control_mapping_fallback(config, kind=kind), resolved_id
