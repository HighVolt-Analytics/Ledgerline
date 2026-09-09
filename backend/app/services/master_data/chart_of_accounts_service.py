"""Load and persist tenant chart of accounts (rule book config slice)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.account_types import (
    PROVIDER_QBO,
    ledger_type_for_qbo,
    normalize_account_type,
)
from app.integrations.qbo.accounts import (
    QboAccountWriteError,
    children_of,
    create_account_in_qbo,
    get_qbo_account,
    inactivate_account_in_qbo,
    is_system_qbo_account,
    is_top_level_qbo_account,
    list_active_qbo_accounts,
    list_cached_qbo_accounts,
    local_code_for_qbo,
    sub_ledgers_from_children,
    sync_accounts_from_qbo,
    update_account_in_qbo,
)
from app.integrations.qbo.store import QboNotReadyError, require_qbo_ready
from app.integrations.xero.account_types import (
    PROVIDER_XERO,
    ledger_type_for_xero,
    normalize_subtype,
)
from app.integrations.xero.accounts import (
    XeroAccountWriteError,
    create_account_in_xero,
    delete_account_in_xero,
    get_xero_account,
    is_system_xero_account,
    list_active_xero_accounts,
    sync_accounts_from_xero,
    update_account_in_xero,
)
from app.models.qbo_account import QboAccount
from app.integrations.xero.client import XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.schemas.chart_of_accounts import (
    ChartOfAccountsResponse,
    PlatformChartOfAccount,
    UpdateChartOfAccountsRequest,
    UpsertXeroChartOfAccountRequest,
)
from app.schemas.rule_book_config import (
    ChartOfAccountEntry,
    ChartOfAccountType,
    SubLedgerEntry,
    validate_rule_book_config_payload,
)
from app.schemas.tax_rates import BillProcessingTaxProvider
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config


async def _qbo_connection(
    session: AsyncSession,
    tenant_id: uuid.UUID,
):
    try:
        return await require_qbo_ready(session, tenant_id)
    except (RuntimeError, QboNotReadyError):
        return None


def _qbo_provider(integration: object) -> BillProcessingTaxProvider:
    organisation = getattr(integration, "display_name", None)
    organisation_name = str(organisation).strip() if organisation else None
    return BillProcessingTaxProvider(
        id="quickbooks_online",
        name="QuickBooks",
        organisation_name=organisation_name or None,
        connected=True,
    )


async def _xero_connection(
    session: AsyncSession,
    tenant_id: uuid.UUID,
):
    try:
        return await require_xero_ready(session, tenant_id)
    except RuntimeError:
        return None


def _xero_provider(integration: object) -> BillProcessingTaxProvider:
    organisation = getattr(integration, "display_name", None)
    organisation_name = str(organisation).strip() if organisation else None
    return BillProcessingTaxProvider(
        id="xero",
        name="Xero",
        organisation_name=organisation_name or None,
        connected=True,
    )


def _code_key(code: str | None) -> str:
    return (code or "").strip().upper()


def _without_provider(entry: ChartOfAccountEntry, provider: str) -> ChartOfAccountEntry:
    linked = [item for item in entry.linked_providers if item != provider]
    return entry.model_copy(update={"linked_providers": linked})


def _with_provider(entry: ChartOfAccountEntry, provider: str) -> ChartOfAccountEntry:
    linked = list(entry.linked_providers)
    if provider not in linked:
        linked.append(provider)
    return entry.model_copy(update={"linked_providers": linked})


def _clip_entry(
    *,
    code: str,
    name: str,
    ledger_type: ChartOfAccountType,
    sub_type: str | None,
    linked_providers: list[str],
    sub_ledgers: list[SubLedgerEntry],
) -> ChartOfAccountEntry:
    return ChartOfAccountEntry(
        code=code.strip()[:32],
        name=name.strip()[:128],
        type=ledger_type,
        sub_type=sub_type,
        linked_providers=linked_providers,
        sub_ledgers=list(sub_ledgers),
    )


def _name_taken(entries: list[ChartOfAccountEntry], name: str, *, except_code: str | None = None) -> bool:
    needle = name.strip().lower()
    skip = _code_key(except_code)
    return any(
        item.name.strip().lower() == needle and _code_key(item.code) != skip
        for item in entries
    )


def _unique_name(entries: list[ChartOfAccountEntry], name: str, *, except_code: str | None = None) -> str:
    cleaned = name.strip()[:128] or "Account"
    if not _name_taken(entries, cleaned, except_code=except_code):
        return cleaned
    suffix = f" ({(except_code or '').strip()})" if (except_code or "").strip() else " (remote)"
    base = cleaned[: max(1, 128 - len(suffix))]
    candidate = f"{base}{suffix}"[:128]
    if not _name_taken(entries, candidate, except_code=except_code):
        return candidate
    raise XeroAccountWriteError(
        f"A local account named {cleaned!r} already exists. Rename it before continuing."
    )


def _upsert_linked(
    entries: list[ChartOfAccountEntry],
    next_entry: ChartOfAccountEntry,
    *,
    match_key: str,
) -> list[ChartOfAccountEntry]:
    new_key = _code_key(next_entry.code)
    match = _code_key(match_key) or new_key
    out: list[ChartOfAccountEntry] = []
    replaced = False
    for item in entries:
        key = _code_key(item.code)
        if key == match or key == new_key:
            if not replaced:
                out.append(next_entry)
                replaced = True
            continue
        out.append(item)
    if not replaced:
        out.append(next_entry)
    return out


def _by_code(entries: list[ChartOfAccountEntry]) -> dict[str, ChartOfAccountEntry]:
    return {_code_key(item.code): item for item in entries if item.code.strip()}


async def _entries(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[ChartOfAccountEntry]:
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    return list(payload.chart_of_accounts)


async def _persist_entries(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entries: list[ChartOfAccountEntry],
    *,
    updated_by_user_id: int | None,
) -> list[ChartOfAccountEntry]:
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    merged = payload.model_dump()
    merged["chart_of_accounts"] = [entry.model_dump() for entry in entries]
    updated = validate_rule_book_config_payload(merged)
    await save_rule_book_config(
        session,
        updated,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
    clear_rule_book_cache()
    return list(updated.chart_of_accounts)


def _qbo_platform_row(
    row: QboAccount,
    local: ChartOfAccountEntry | None,
    children: list[QboAccount],
    *,
    in_catalogue: bool,
) -> PlatformChartOfAccount:
    locked = is_system_qbo_account(row)
    ledger_type = ledger_type_for_qbo(
        account_type=row.account_type,
        classification=row.classification,
    )
    subtype = normalize_account_type(ledger_type, row.account_type)
    providers = list(local.linked_providers) if local else []
    if PROVIDER_QBO not in providers:
        providers = [*providers, PROVIDER_QBO]
    sub_ledgers = list(local.sub_ledgers) if local else sub_ledgers_from_children(children)
    return PlatformChartOfAccount(
        xero_account_id=row.qbo_account_id,
        code=local_code_for_qbo(row),
        name=(row.name or (local.name if local else "") or "").strip(),
        type=ledger_type,
        sub_type=subtype,
        can_edit=not locked,
        can_delete=not locked,
        can_pull=not in_catalogue,
        linked_providers=providers,
        sub_ledgers=sub_ledgers,
        status="ACTIVE" if row.active else "INACTIVE",
    )


async def _qbo_connected_payload(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entries: list[ChartOfAccountEntry],
    integration: object,
    realm_id: str,
) -> ChartOfAccountsResponse:
    qbo_rows = await list_active_qbo_accounts(session, tenant_id, realm_id)
    catalogue = _by_code(entries)
    qbo_codes = {_code_key(local_code_for_qbo(row)) for row in qbo_rows if is_top_level_qbo_account(row)}
    local_accounts = [entry for entry in entries if _code_key(entry.code) not in qbo_codes]
    platform_accounts = [
        _qbo_platform_row(
            row,
            catalogue.get(_code_key(local_code_for_qbo(row))),
            children_of(row.qbo_account_id, qbo_rows),
            in_catalogue=_code_key(local_code_for_qbo(row)) in catalogue,
        )
        for row in qbo_rows
        if is_top_level_qbo_account(row)
    ]
    return ChartOfAccountsResponse(
        accounts=list(entries),
        local_accounts=local_accounts,
        platform_accounts=platform_accounts,
        xero_connected=False,
        source="quickbooks_online",
        provider=_qbo_provider(integration),
    )


def _platform_row(
    row: XeroAccount,
    local: ChartOfAccountEntry | None,
    *,
    in_catalogue: bool,
) -> PlatformChartOfAccount:
    locked = is_system_xero_account(row)
    ledger_type = ledger_type_for_xero(account_type=row.account_type, account_class=row.account_class)
    subtype = normalize_subtype(ledger_type, row.account_type)
    providers = list(local.linked_providers) if local else []
    if PROVIDER_XERO not in providers:
        providers = [*providers, PROVIDER_XERO]
    return PlatformChartOfAccount(
        xero_account_id=row.xero_account_id,
        code=(row.code or (local.code if local else "") or "").strip(),
        name=(row.name or (local.name if local else "") or "").strip(),
        type=ledger_type,
        sub_type=subtype,
        can_edit=not locked,
        can_delete=not locked,
        can_pull=not in_catalogue,
        linked_providers=providers,
        sub_ledgers=list(local.sub_ledgers) if local else [],
        status=row.status,
    )


async def _connected_payload(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entries: list[ChartOfAccountEntry],
    integration: object,
    xero_tenant_id: str,
) -> ChartOfAccountsResponse:
    xero_rows = await list_active_xero_accounts(session, tenant_id, xero_tenant_id)
    catalogue = _by_code(entries)
    xero_codes = {_code_key(row.code) for row in xero_rows if (row.code or "").strip()}
    local_accounts = [entry for entry in entries if _code_key(entry.code) not in xero_codes]
    platform_accounts = [
        _platform_row(
            row,
            catalogue.get(_code_key(row.code)),
            in_catalogue=_code_key(row.code) in catalogue,
        )
        for row in xero_rows
        if (row.code or "").strip() or row.name
    ]
    return ChartOfAccountsResponse(
        accounts=list(entries),
        local_accounts=local_accounts,
        platform_accounts=platform_accounts,
        xero_connected=True,
        source="xero",
        provider=_xero_provider(integration),
    )


async def load_chart_of_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> ChartOfAccountsResponse:
    entries = await _entries(session, tenant_id)
    qbo = await _qbo_connection(session, tenant_id)
    if qbo is not None:
        integration, realm_id = qbo
        return await _qbo_connected_payload(session, tenant_id, entries, integration, realm_id)
    connected = await _xero_connection(session, tenant_id)
    if connected is None:
        return ChartOfAccountsResponse.from_entries(entries)
    integration, xero_tenant_id = connected
    return await _connected_payload(session, tenant_id, entries, integration, xero_tenant_id)


async def save_chart_of_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpdateChartOfAccountsRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    incoming = body.to_entries()
    qbo = await _qbo_connection(session, tenant_id)
    if qbo is not None:
        _integration, realm_id = qbo
        existing = await _entries(session, tenant_id)
        qbo_rows = await list_active_qbo_accounts(session, tenant_id, realm_id)
        qbo_codes = {
            _code_key(local_code_for_qbo(row))
            for row in qbo_rows
            if is_top_level_qbo_account(row)
        }
        seen = {_code_key(entry.code) for entry in incoming}
        merged = list(incoming)
        for entry in existing:
            key = _code_key(entry.code)
            if key in seen:
                continue
            if key in qbo_codes:
                merged.append(entry)
        await _persist_entries(
            session,
            tenant_id,
            merged,
            updated_by_user_id=updated_by_user_id,
        )
        return await load_chart_of_accounts(session, tenant_id)
    connected = await _xero_connection(session, tenant_id)
    if connected is None:
        await _persist_entries(
            session,
            tenant_id,
            incoming,
            updated_by_user_id=updated_by_user_id,
        )
        return await load_chart_of_accounts(session, tenant_id)

    _integration, xero_tenant_id = connected
    existing = await _entries(session, tenant_id)
    xero_rows = await list_active_xero_accounts(session, tenant_id, xero_tenant_id)
    xero_codes = {_code_key(row.code) for row in xero_rows if (row.code or "").strip()}
    seen = {_code_key(entry.code) for entry in incoming}
    merged = list(incoming)
    for entry in existing:
        key = _code_key(entry.code)
        if key in seen:
            continue
        if key in xero_codes:
            merged.append(entry)
    await _persist_entries(
        session,
        tenant_id,
        merged,
        updated_by_user_id=updated_by_user_id,
    )
    return await load_chart_of_accounts(session, tenant_id)


async def sync_chart_of_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> ChartOfAccountsResponse:
    if await _qbo_connection(session, tenant_id) is not None:
        try:
            await sync_accounts_from_qbo(session, tenant_id)
        except QboAccountWriteError:
            raise
        except Exception as exc:
            raise QboAccountWriteError(
                str(exc) or "Could not sync accounts from QuickBooks",
                status_code=502,
            ) from exc
        return await load_chart_of_accounts(session, tenant_id)
    if await _xero_connection(session, tenant_id) is None:
        raise XeroAccountWriteError(
            "Connect Xero or QuickBooks in Integrations before syncing accounts.",
            status_code=400,
        )
    try:
        await sync_accounts_from_xero(session, tenant_id)
    except XeroApiError as exc:
        raise XeroAccountWriteError(
            exc.message or "Could not sync accounts from Xero",
            status_code=exc.status_code or 502,
        ) from exc
    return await load_chart_of_accounts(session, tenant_id)


async def create_xero_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpsertXeroChartOfAccountRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    entries = await _entries(session, tenant_id)
    key = _code_key(body.code)
    if _name_taken(entries, body.name, except_code=key):
        raise XeroAccountWriteError(
            f"A local account named {body.name.strip()!r} already exists. Rename it before pushing."
        )
    subtype = normalize_subtype(body.type, body.sub_type)
    created = await create_account_in_xero(
        session,
        tenant_id,
        code=body.code,
        name=body.name,
        xero_type=subtype,
    )
    entries = await _entries(session, tenant_id)
    catalogue = _by_code(entries)
    key = _code_key(created.code or body.code)
    existing = catalogue.get(key)
    next_entry = _clip_entry(
        code=(created.code or body.code),
        name=(created.name or body.name),
        ledger_type=body.type,
        sub_type=subtype,
        linked_providers=[PROVIDER_XERO],
        sub_ledgers=list(existing.sub_ledgers if existing is not None else body.sub_ledgers),
    )
    entries = _upsert_linked(entries, next_entry, match_key=key)
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def _persist_locked_sub_ledgers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    cached_code: str,
    cached_name: str,
    ledger_type: ChartOfAccountType,
    subtype: str,
    sub_ledgers: list[SubLedgerEntry],
    updated_by_user_id: int | None,
    provider: str = PROVIDER_XERO,
) -> ChartOfAccountsResponse:
    entries = await _entries(session, tenant_id)
    key = _code_key(cached_code)
    if not key:
        raise XeroAccountWriteError("This account has no code to store locally.")
    existing = _by_code(entries).get(key)
    next_entry = _clip_entry(
        code=cached_code,
        name=(existing.name if existing is not None else cached_name) or cached_code,
        ledger_type=existing.type if existing is not None else ledger_type,
        sub_type=existing.sub_type if existing is not None else subtype,
        linked_providers=_with_provider(existing, provider).linked_providers
        if existing is not None
        else [provider],
        sub_ledgers=list(sub_ledgers),
    )
    entries = _upsert_linked(entries, next_entry, match_key=key)
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def update_xero_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    xero_account_id: str,
    body: UpsertXeroChartOfAccountRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    connected = await _xero_connection(session, tenant_id)
    if connected is None:
        raise XeroAccountWriteError("Connect Xero in Integrations first.", status_code=400)
    _integration, xero_tenant_id = connected
    cached = await get_xero_account(session, tenant_id, xero_tenant_id, xero_account_id)
    if cached is None:
        raise XeroAccountWriteError("Xero account not found", status_code=404)
    if is_system_xero_account(cached):
        ledger_type = ledger_type_for_xero(
            account_type=cached.account_type,
            account_class=cached.account_class,
        )
        return await _persist_locked_sub_ledgers(
            session,
            tenant_id,
            cached_code=cached.code or body.code,
            cached_name=cached.name or body.name,
            ledger_type=ledger_type,
            subtype=normalize_subtype(ledger_type, cached.account_type),
            sub_ledgers=list(body.sub_ledgers),
            updated_by_user_id=updated_by_user_id,
        )
    subtype = normalize_subtype(body.type, body.sub_type)
    old_key = _code_key(cached.code or body.code)
    new_key = _code_key(body.code)
    entries = await _entries(session, tenant_id)
    if new_key != old_key and new_key in _by_code(entries):
        raise XeroAccountWriteError("That account code already exists in the local chart of accounts.")
    if _name_taken(entries, body.name, except_code=old_key or new_key):
        raise XeroAccountWriteError(
            f"A local account named {body.name.strip()!r} already exists."
        )
    updated = await update_account_in_xero(
        session,
        tenant_id,
        xero_account_id,
        code=body.code,
        name=body.name,
        xero_type=subtype,
    )
    entries = await _entries(session, tenant_id)
    new_key = _code_key(updated.code or body.code)
    existing = _by_code(entries).get(old_key) or _by_code(entries).get(new_key)
    next_entry = _clip_entry(
        code=(updated.code or body.code),
        name=(updated.name or body.name),
        ledger_type=body.type,
        sub_type=subtype,
        linked_providers=_with_provider(existing, PROVIDER_XERO).linked_providers
        if existing is not None
        else [PROVIDER_XERO],
        sub_ledgers=list(body.sub_ledgers),
    )
    entries = _upsert_linked(entries, next_entry, match_key=old_key or new_key)
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def delete_xero_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    xero_account_id: str,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    deleted = await delete_account_in_xero(session, tenant_id, xero_account_id)
    entries = await _entries(session, tenant_id)
    key = _code_key(deleted.code)
    if not key:
        return await load_chart_of_accounts(session, tenant_id)
    catalogue = _by_code(entries)
    existing = catalogue.get(key)
    if existing is None:
        ledger_type = ledger_type_for_xero(
            account_type=deleted.account_type,
            account_class=deleted.account_class,
        )
        entries.append(
            _clip_entry(
                code=deleted.code or "",
                name=deleted.name or "Xero account",
                ledger_type=ledger_type,
                sub_type=deleted.account_type,
                linked_providers=[],
                sub_ledgers=[],
            )
        )
    else:
        entries = [
            _without_provider(item, PROVIDER_XERO) if _code_key(item.code) == key else item
            for item in entries
        ]
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def pull_xero_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    xero_account_id: str,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    connected = await _xero_connection(session, tenant_id)
    if connected is None:
        raise XeroAccountWriteError("Connect Xero in Integrations first.", status_code=400)
    _integration, xero_tenant_id = connected
    row = await get_xero_account(session, tenant_id, xero_tenant_id, xero_account_id)
    if row is None or (row.status or "ACTIVE").upper() != "ACTIVE":
        raise XeroAccountWriteError("Xero account not found", status_code=404)
    key = _code_key(row.code)
    if not key:
        raise XeroAccountWriteError("This Xero account has no code to pull.")
    entries = await _entries(session, tenant_id)
    if key in _by_code(entries):
        raise XeroAccountWriteError("This account already exists in the local chart of accounts.")
    ledger_type = ledger_type_for_xero(account_type=row.account_type, account_class=row.account_class)
    entries.append(
        _clip_entry(
            code=row.code or "",
            name=_unique_name(entries, (row.name or "").strip() or (row.code or "Account"), except_code=key),
            ledger_type=ledger_type,
            sub_type=row.account_type,
            linked_providers=[PROVIDER_XERO],
            sub_ledgers=[],
        )
    )
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def _ensure_qbo_subaccounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
    parent: QboAccount,
    sub_ledgers: list[SubLedgerEntry],
    account_type: str,
) -> None:
    rows = await list_cached_qbo_accounts(session, tenant_id, realm_id)
    remaining = children_of(parent.qbo_account_id, rows, active_only=False)
    for sub in sub_ledgers:
        code_key = _code_key(sub.code)
        name_key = sub.name.strip().lower()
        match = next(
            (
                child
                for child in remaining
                if _code_key(local_code_for_qbo(child)) == code_key
                or (child.name or "").strip().lower() == name_key
            ),
            None,
        )
        if match is not None:
            remaining = [child for child in remaining if child.qbo_account_id != match.qbo_account_id]
            if is_system_qbo_account(match):
                continue
            await update_account_in_qbo(
                session,
                tenant_id,
                match.qbo_account_id,
                code=sub.code,
                name=sub.name,
                account_type=account_type,
            )
            continue
        await create_account_in_qbo(
            session,
            tenant_id,
            code=sub.code,
            name=sub.name,
            account_type=account_type,
            parent_id=parent.qbo_account_id,
        )
    for leftover in remaining:
        if is_system_qbo_account(leftover) or not leftover.active:
            continue
        await inactivate_account_in_qbo(session, tenant_id, leftover.qbo_account_id)


async def create_qbo_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpsertXeroChartOfAccountRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    entries = await _entries(session, tenant_id)
    key = _code_key(body.code)
    if _name_taken(entries, body.name, except_code=key):
        raise QboAccountWriteError(
            f"A local account named {body.name.strip()!r} already exists. Rename it before pushing."
        )
    account_type = normalize_account_type(body.type, body.sub_type)
    created = await create_account_in_qbo(
        session,
        tenant_id,
        code=body.code,
        name=body.name,
        account_type=account_type,
    )
    connected = await _qbo_connection(session, tenant_id)
    realm_id = connected[1] if connected is not None else ""
    await _ensure_qbo_subaccounts(
        session,
        tenant_id,
        realm_id,
        created,
        list(body.sub_ledgers),
        account_type,
    )
    entries = await _entries(session, tenant_id)
    catalogue = _by_code(entries)
    key = _code_key(local_code_for_qbo(created) or body.code)
    existing = catalogue.get(key)
    next_entry = _clip_entry(
        code=local_code_for_qbo(created) or body.code,
        name=(created.name or body.name),
        ledger_type=body.type,
        sub_type=account_type,
        linked_providers=[PROVIDER_QBO],
        sub_ledgers=list(existing.sub_ledgers if existing is not None else body.sub_ledgers),
    )
    entries = _upsert_linked(entries, next_entry, match_key=key)
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def update_qbo_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    qbo_account_id: str,
    body: UpsertXeroChartOfAccountRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    connected = await _qbo_connection(session, tenant_id)
    if connected is None:
        raise QboAccountWriteError("Connect QuickBooks in Integrations first.", status_code=400)
    _integration, realm_id = connected
    cached = await get_qbo_account(session, tenant_id, realm_id, qbo_account_id)
    if cached is None:
        raise QboAccountWriteError("QuickBooks account not found", status_code=404)
    account_type = normalize_account_type(body.type, body.sub_type)
    old_key = _code_key(local_code_for_qbo(cached) or body.code)
    if is_system_qbo_account(cached):
        await _ensure_qbo_subaccounts(
            session, tenant_id, realm_id, cached, list(body.sub_ledgers), account_type
        )
        return await _persist_locked_sub_ledgers(
            session,
            tenant_id,
            cached_code=local_code_for_qbo(cached) or body.code,
            cached_name=cached.name or body.name,
            ledger_type=ledger_type_for_qbo(
                account_type=cached.account_type,
                classification=cached.classification,
            ),
            subtype=account_type,
            sub_ledgers=list(body.sub_ledgers),
            updated_by_user_id=updated_by_user_id,
            provider=PROVIDER_QBO,
        )
    new_key = _code_key(body.code)
    entries = await _entries(session, tenant_id)
    if new_key != old_key and new_key in _by_code(entries):
        raise QboAccountWriteError("That account code already exists in the local chart of accounts.")
    if _name_taken(entries, body.name, except_code=old_key or new_key):
        raise QboAccountWriteError(f"A local account named {body.name.strip()!r} already exists.")
    updated = await update_account_in_qbo(
        session,
        tenant_id,
        qbo_account_id,
        code=body.code,
        name=body.name,
        account_type=account_type,
    )
    await _ensure_qbo_subaccounts(
        session, tenant_id, realm_id, updated, list(body.sub_ledgers), account_type
    )
    entries = await _entries(session, tenant_id)
    new_key = _code_key(local_code_for_qbo(updated) or body.code)
    existing = _by_code(entries).get(old_key) or _by_code(entries).get(new_key)
    next_entry = _clip_entry(
        code=local_code_for_qbo(updated) or body.code,
        name=(updated.name or body.name),
        ledger_type=body.type,
        sub_type=account_type,
        linked_providers=_with_provider(existing, PROVIDER_QBO).linked_providers
        if existing is not None
        else [PROVIDER_QBO],
        sub_ledgers=list(body.sub_ledgers),
    )
    entries = _upsert_linked(entries, next_entry, match_key=old_key or new_key)
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def delete_qbo_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    qbo_account_id: str,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    connected = await _qbo_connection(session, tenant_id)
    if connected is None:
        raise QboAccountWriteError("Connect QuickBooks in Integrations first.", status_code=400)
    _integration, realm_id = connected
    rows = await list_active_qbo_accounts(session, tenant_id, realm_id)
    for child in children_of(qbo_account_id, rows):
        if not is_system_qbo_account(child):
            await inactivate_account_in_qbo(session, tenant_id, child.qbo_account_id)
    deleted = await inactivate_account_in_qbo(session, tenant_id, qbo_account_id)
    entries = await _entries(session, tenant_id)
    key = _code_key(local_code_for_qbo(deleted))
    if not key:
        return await load_chart_of_accounts(session, tenant_id)
    catalogue = _by_code(entries)
    existing = catalogue.get(key)
    if existing is None:
        ledger_type = ledger_type_for_qbo(
            account_type=deleted.account_type,
            classification=deleted.classification,
        )
        entries.append(
            _clip_entry(
                code=local_code_for_qbo(deleted),
                name=deleted.name or "QuickBooks account",
                ledger_type=ledger_type,
                sub_type=deleted.account_type,
                linked_providers=[],
                sub_ledgers=sub_ledgers_from_children(children_of(qbo_account_id, rows)),
            )
        )
    else:
        entries = [
            _without_provider(item, PROVIDER_QBO) if _code_key(item.code) == key else item
            for item in entries
        ]
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


async def pull_qbo_chart_of_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    qbo_account_id: str,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    connected = await _qbo_connection(session, tenant_id)
    if connected is None:
        raise QboAccountWriteError("Connect QuickBooks in Integrations first.", status_code=400)
    _integration, realm_id = connected
    row = await get_qbo_account(session, tenant_id, realm_id, qbo_account_id)
    if row is None or not row.active:
        raise QboAccountWriteError("QuickBooks account not found", status_code=404)
    key = _code_key(local_code_for_qbo(row))
    if not key:
        raise QboAccountWriteError("This QuickBooks account has no code to pull.")
    entries = await _entries(session, tenant_id)
    if key in _by_code(entries):
        raise QboAccountWriteError("This account already exists in the local chart of accounts.")
    qbo_rows = await list_active_qbo_accounts(session, tenant_id, realm_id)
    ledger_type = ledger_type_for_qbo(account_type=row.account_type, classification=row.classification)
    entries.append(
        _clip_entry(
            code=local_code_for_qbo(row),
            name=_unique_name(entries, (row.name or "").strip() or local_code_for_qbo(row), except_code=key),
            ledger_type=ledger_type,
            sub_type=row.account_type,
            linked_providers=[PROVIDER_QBO],
            sub_ledgers=sub_ledgers_from_children(children_of(row.qbo_account_id, qbo_rows)),
        )
    )
    await _persist_entries(session, tenant_id, entries, updated_by_user_id=updated_by_user_id)
    return await load_chart_of_accounts(session, tenant_id)


def coa_lookup(entries: list[ChartOfAccountEntry]) -> dict[str, ChartOfAccountEntry]:
    return {entry.name.strip(): entry for entry in entries if entry.name.strip()}


def sub_ledgers_for_ledger(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> list[SubLedgerEntry]:
    cleaned = (ledger_name or "").strip()
    if not cleaned:
        return []
    lookup = coa_lookup(entries)
    entry = lookup.get(cleaned)
    if entry is None:
        lowered = cleaned.lower()
        for name, candidate in lookup.items():
            if name.lower() == lowered:
                entry = candidate
                break
    if entry is None:
        return []
    return list(entry.sub_ledgers)


def sub_ledger_exists(
    ledger_name: str,
    sub_ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    """True when sub_ledger_name matches a catalog entry under the given ledger."""
    cleaned_sub = (sub_ledger_name or "").strip()
    if not cleaned_sub:
        return False
    sub_ledgers = sub_ledgers_for_ledger(ledger_name, entries)
    if not sub_ledgers:
        return False
    lowered = cleaned_sub.lower()
    for item in sub_ledgers:
        if item.name.strip().lower() == lowered:
            return True
    return False


def ledger_has_sub_ledger_catalog(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    return bool(sub_ledgers_for_ledger(ledger_name, entries))


def _find_coa_entry(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> ChartOfAccountEntry | None:
    cleaned = (ledger_name or "").strip()
    if not cleaned:
        return None
    lookup = coa_lookup(entries)
    entry = lookup.get(cleaned)
    if entry is not None:
        return entry
    lowered = cleaned.lower()
    for name, candidate in lookup.items():
        if name.lower() == lowered:
            return candidate
    return None


def parent_ledger_for_account(
    account_name: str,
    entries: list[ChartOfAccountEntry],
) -> str | None:
    """Return the budget parent for an account name.

    - If ``account_name`` is a known parent COA row, return that parent name.
    - If it matches a sub-ledger under a parent, return that parent name.
    - Otherwise return None.
    """
    cleaned = (account_name or "").strip()
    if not cleaned:
        return None
    direct = _find_coa_entry(cleaned, entries)
    if direct is not None:
        return direct.name.strip()
    lowered = cleaned.lower()
    for entry in entries:
        parent = (entry.name or "").strip()
        if not parent:
            continue
        for sub in entry.sub_ledgers or []:
            if (sub.name or "").strip().lower() == lowered:
                return parent
            if (sub.code or "").strip().lower() == lowered:
                return parent
    return None


def account_is_sub_ledger(
    account_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    """True when ``account_name`` is a COA child Sub-GL (not a top-level parent)."""
    cleaned = (account_name or "").strip()
    if not cleaned:
        return False
    if _find_coa_entry(cleaned, entries) is not None:
        return False
    parent = parent_ledger_for_account(cleaned, entries)
    if not parent:
        return False
    return parent.casefold() != cleaned.casefold()


def child_ledger_names(
    parent_ledger: str,
    entries: list[ChartOfAccountEntry],
) -> list[str]:
    """Parent name plus all of its COA sub-ledger names (and codes when distinct).

    Used to sum budget spend across a parent wallet and its tracking children.
    """
    parent = (parent_ledger or "").strip()
    if not parent:
        return []
    entry = _find_coa_entry(parent, entries)
    names: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        cleaned = (token or "").strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(cleaned)

    if entry is not None:
        _add(entry.name)
        _add(entry.code)
        for sub in entry.sub_ledgers or []:
            _add(sub.name)
            _add(sub.code)
    else:
        _add(parent)
    return names


def budget_parent_for_claim_gl(
    claim_gl: str,
    entries: list[ChartOfAccountEntry],
    *,
    fallback_parent: str | None = None,
) -> str:
    """Resolve which parent wallet a claim GL should check against."""
    resolved = parent_ledger_for_account(claim_gl, entries)
    if resolved:
        return resolved
    fallback = (fallback_parent or "").strip()
    if fallback:
        parent = parent_ledger_for_account(fallback, entries)
        return parent or fallback
    return (claim_gl or "").strip()
