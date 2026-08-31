"""Load and persist tenant tax rates (Xero when connected, else rule book)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.client import XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.integrations.xero.tax_rates import (
    XeroTaxRateWriteError,
    create_tax_rate_in_xero,
    delete_tax_rate_in_xero,
    list_synced_tax_rates,
    sync_tax_rates_from_xero,
    update_tax_rate_in_xero,
)
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.schemas.tax_rates import (
    CreateTaxRateRequest,
    TaxRateEntry,
    TaxRatesResponse,
    UpdateTaxRateRequest,
    UpdateTaxRatesRequest,
)
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config


async def xero_connection(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> tuple[object, str] | None:
    try:
        return await require_xero_ready(session, tenant_id)
    except RuntimeError:
        return None


async def load_tax_rates(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> TaxRatesResponse:
    connected = await xero_connection(session, tenant_id)
    if connected is not None:
        _integration, xero_tenant_id = connected
        entries = await list_synced_tax_rates(session, tenant_id, xero_tenant_id)
        return TaxRatesResponse.from_entries(entries, xero_connected=True)
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    return TaxRatesResponse.from_entries(payload.tax_rates, xero_connected=False)


async def save_tax_rates(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpdateTaxRatesRequest,
    *,
    updated_by_user_id: int | None = None,
) -> TaxRatesResponse:
    if await xero_connection(session, tenant_id) is not None:
        raise XeroTaxRateWriteError(
            "Xero is connected. Add or delete tax rates individually so they stay in sync.",
            status_code=409,
        )
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    merged = payload.model_dump()
    merged["tax_rates"] = [
        entry.model_dump(exclude={"total_rate"}) for entry in body.to_entries()
    ]
    updated = validate_rule_book_config_payload(merged)
    await save_rule_book_config(
        session,
        updated,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
    clear_rule_book_cache()
    return TaxRatesResponse.from_entries(updated.tax_rates, xero_connected=False)


async def create_tax_rate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: CreateTaxRateRequest,
    *,
    updated_by_user_id: int | None = None,
) -> TaxRatesResponse:
    connected = await xero_connection(session, tenant_id)
    if connected is not None:
        try:
            await create_tax_rate_in_xero(
                session,
                tenant_id,
                display_name=body.display_name,
                report_type=body.tax_type,
                components=body.components,
            )
        except XeroApiError as exc:
            raise XeroTaxRateWriteError(
                exc.message or "Xero rejected the tax rate",
                status_code=exc.status_code or 502,
            ) from exc
        return await load_tax_rates(session, tenant_id)

    current = await load_tax_rates(session, tenant_id)
    names = {row.display_name.strip().lower() for row in current.tax_rates}
    if body.display_name.strip().lower() in names:
        raise XeroTaxRateWriteError("A tax rate with this name already exists.")
    entry = TaxRateEntry(
        display_name=body.display_name,
        tax_type=body.tax_type,
        components=body.components,
        source="local",
        can_delete=True,
        can_edit=True,
    )
    return await save_tax_rates(
        session,
        tenant_id,
        UpdateTaxRatesRequest(tax_rates=[*current.tax_rates, entry]),
        updated_by_user_id=updated_by_user_id,
    )


async def delete_tax_rate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    rate_id: str,
    *,
    updated_by_user_id: int | None = None,
) -> TaxRatesResponse:
    connected = await xero_connection(session, tenant_id)
    if connected is not None:
        await delete_tax_rate_in_xero(session, tenant_id, rate_id)
        return await load_tax_rates(session, tenant_id)

    current = await load_tax_rates(session, tenant_id)
    remaining = [row for row in current.tax_rates if row.id != rate_id]
    if len(remaining) == len(current.tax_rates):
        raise XeroTaxRateWriteError("Tax rate not found", status_code=404)
    return await save_tax_rates(
        session,
        tenant_id,
        UpdateTaxRatesRequest(tax_rates=remaining),
        updated_by_user_id=updated_by_user_id,
    )


async def update_tax_rate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    rate_id: str,
    body: UpdateTaxRateRequest,
    *,
    updated_by_user_id: int | None = None,
) -> TaxRatesResponse:
    connected = await xero_connection(session, tenant_id)
    if connected is not None:
        try:
            await update_tax_rate_in_xero(
                session,
                tenant_id,
                rate_id,
                display_name=body.display_name,
                report_type=body.tax_type,
                components=body.components,
            )
        except XeroApiError as exc:
            raise XeroTaxRateWriteError(
                exc.message or "Xero rejected the tax rate update",
                status_code=exc.status_code or 502,
            ) from exc
        return await load_tax_rates(session, tenant_id)

    current = await load_tax_rates(session, tenant_id)
    index = next((i for i, row in enumerate(current.tax_rates) if row.id == rate_id), -1)
    if index < 0:
        raise XeroTaxRateWriteError("Tax rate not found", status_code=404)
    existing = current.tax_rates[index]
    if not existing.can_edit:
        raise XeroTaxRateWriteError("This tax rate cannot be edited.")
    name_key = body.display_name.strip().lower()
    for i, row in enumerate(current.tax_rates):
        if i != index and row.display_name.strip().lower() == name_key:
            raise XeroTaxRateWriteError("A tax rate with this name already exists.")
    updated = existing.model_copy(
        update={
            "display_name": body.display_name,
            "tax_type": body.tax_type,
            "components": body.components,
        }
    )
    next_rows = list(current.tax_rates)
    next_rows[index] = updated
    return await save_tax_rates(
        session,
        tenant_id,
        UpdateTaxRatesRequest(tax_rates=next_rows),
        updated_by_user_id=updated_by_user_id,
    )


async def sync_tax_rates(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> TaxRatesResponse:
    if await xero_connection(session, tenant_id) is None:
        raise XeroTaxRateWriteError(
            "Connect Xero in Integrations before syncing tax rates.",
            status_code=400,
        )
    try:
        await sync_tax_rates_from_xero(session, tenant_id)
    except XeroApiError as exc:
        raise XeroTaxRateWriteError(
            exc.message or "Could not sync tax rates from Xero",
            status_code=exc.status_code or 502,
        ) from exc
    return await load_tax_rates(session, tenant_id)
