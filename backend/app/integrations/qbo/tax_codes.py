"""Pull QuickBooks TaxCode + TaxRate into Settings → Tax rates."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.client import QboApiClient, QboApiError
from app.integrations.qbo.store import require_qbo_ready
from app.integrations.xero.sync_counts import EntitySyncCounters, payload_hash
from app.models.qbo_tax_code import SOURCE_SYSTEM_QBO, QboTaxCode
from app.schemas.tax_rates import TaxRateComponent, TaxRateEntry
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"
_PAGE_SIZE = 1000


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _query_all(client: QboApiClient, entity_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 1
    while True:
        statement = (
            f"SELECT * FROM {entity_name} STARTPOSITION {start} MAXRESULTS {_PAGE_SIZE}"
        )
        payload = await client.query(statement)
        query = payload.get("QueryResponse") or {}
        batch = _as_list(query.get(entity_name))
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


def _rate_map(tax_rates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in tax_rates:
        rate_id = str(row.get("Id") or "").strip()
        if rate_id:
            mapped[rate_id] = row
    return mapped


def _details(block: Any) -> list[dict[str, Any]]:
    if not isinstance(block, dict):
        return []
    return _as_list(block.get("TaxRateDetail"))


def _sum_rate(details: list[dict[str, Any]], rates: dict[str, dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for detail in details:
        ref = detail.get("TaxRateRef") if isinstance(detail.get("TaxRateRef"), dict) else {}
        rate_id = str((ref or {}).get("value") or "").strip()
        row = rates.get(rate_id) or {}
        amount = _decimal(row.get("RateValue")) or Decimal("0")
        total += amount
    return total


def _components(
    details: list[dict[str, Any]],
    rates: dict[str, dict[str, Any]],
    *,
    fallback_name: str,
    fallback_rate: Decimal,
) -> list[TaxRateComponent]:
    rows: list[TaxRateComponent] = []
    for detail in details:
        ref = detail.get("TaxRateRef") if isinstance(detail.get("TaxRateRef"), dict) else {}
        rate_id = str((ref or {}).get("value") or "").strip()
        row = rates.get(rate_id) or {}
        name = str(row.get("Name") or ref.get("name") or fallback_name).strip()[:50] or fallback_name
        rate = float(_decimal(row.get("RateValue")) or 0)
        rows.append(TaxRateComponent(name=name, rate=rate))
    if rows:
        return rows
    return [
        TaxRateComponent(
            name=(fallback_name[:50] or "Tax"),
            rate=float(fallback_rate),
        )
    ]


def _fields_from_tax_code(
    tax_code: dict[str, Any],
    rates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    purchase = _details(tax_code.get("PurchaseTaxRateList"))
    sales = _details(tax_code.get("SalesTaxRateList"))
    return {
        "name": str(tax_code.get("Name") or tax_code.get("Id") or "")[:255] or None,
        "description": str(tax_code.get("Description") or "")[:512] or None,
        "active": bool(tax_code.get("Active", True)),
        "taxable": bool(tax_code.get("Taxable", False)),
        "purchase_rate": _sum_rate(purchase, rates) if purchase else None,
        "sales_rate": _sum_rate(sales, rates) if sales else None,
    }


def tax_code_row_to_entry(row: QboTaxCode) -> TaxRateEntry:
    payload = {}
    if row.raw_payload_json:
        try:
            parsed = json.loads(row.raw_payload_json)
            payload = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    rates_blob = payload.get("_ledgerlink_tax_rates")
    rate_rows = _as_list(rates_blob) if rates_blob else []
    rates = _rate_map(rate_rows)
    purchase = _details(payload.get("PurchaseTaxRateList"))
    sales = _details(payload.get("SalesTaxRateList"))
    name = (row.name or row.qbo_tax_code_id or "Tax").strip()
    if purchase:
        tax_type = "PURCHASES"
        details = purchase
        fallback_rate = row.purchase_rate or Decimal("0")
    elif sales:
        tax_type = "SALES"
        details = sales
        fallback_rate = row.sales_rate or Decimal("0")
    else:
        tax_type = "GST_FREE_EXPENSES"
        details = []
        fallback_rate = Decimal("0")
    return TaxRateEntry(
        id=row.qbo_tax_code_id,
        display_name=name[:50] or row.qbo_tax_code_id,
        tax_type=tax_type,
        components=_components(
            details,
            rates,
            fallback_name=name,
            fallback_rate=fallback_rate,
        ),
        can_delete=False,
        can_edit=False,
        status="ACTIVE" if row.active else "INACTIVE",
        source="quickbooks_online",
    )


async def list_synced_tax_codes(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
) -> list[TaxRateEntry]:
    rows = (
        await db.execute(
            select(QboTaxCode)
            .where(
                QboTaxCode.tenant_id == tenant_id,
                QboTaxCode.realm_id == realm_id,
                QboTaxCode.sync_status == _SYNC_ACTIVE,
            )
            .order_by(QboTaxCode.name, QboTaxCode.qbo_tax_code_id)
        )
    ).scalars().all()
    return [tax_code_row_to_entry(row) for row in rows if row.active]


async def sync_tax_codes_from_qbo(db: AsyncSession, tenant_id: uuid.UUID) -> EntitySyncCounters:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    counters = EntitySyncCounters()
    now = _now()
    tax_rates = await _query_all(client, "TaxRate")
    rates = _rate_map(tax_rates)
    seen: set[str] = set()
    for tax_code in await _query_all(client, "TaxCode"):
        code_id = str(tax_code.get("Id") or "").strip()
        if not code_id:
            continue
        counters.fetched += 1
        seen.add(code_id)
        try:
            stored = dict(tax_code)
            stored["_ledgerlink_tax_rates"] = [
                {"Id": row.get("Id"), "Name": row.get("Name"), "RateValue": row.get("RateValue")}
                for row in tax_rates
            ]
            hash_value = payload_hash(tax_code)
            fields = _fields_from_tax_code(tax_code, rates)
            existing = (
                await db.execute(
                    select(QboTaxCode).where(
                        QboTaxCode.tenant_id == tenant_id,
                        QboTaxCode.realm_id == realm_id,
                        QboTaxCode.qbo_tax_code_id == code_id,
                    )
                )
            ).scalar_one_or_none()
            sync_status = _SYNC_ACTIVE if fields["active"] else _SYNC_INACTIVE
            if existing is None:
                db.add(
                    QboTaxCode(
                        tenant_id=tenant_id,
                        accounting_integration_id=integration.id,
                        realm_id=realm_id,
                        qbo_tax_code_id=code_id,
                        source_system=SOURCE_SYSTEM_QBO,
                        sync_status=sync_status,
                        payload_hash=hash_value,
                        raw_payload_json=json.dumps(stored, default=str),
                        last_seen_at=now,
                        last_synced_at=now,
                        **fields,
                    )
                )
                counters.created += 1
                continue
            if existing.payload_hash == hash_value and existing.sync_status == sync_status:
                existing.last_seen_at = now
                existing.last_synced_at = now
                counters.unchanged += 1
                continue
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.sync_status = sync_status
            existing.payload_hash = hash_value
            existing.raw_payload_json = json.dumps(stored, default=str)
            existing.last_seen_at = now
            existing.last_synced_at = now
            counters.updated += 1
        except Exception as exc:
            counters.failed += 1
            logger.warning(
                "qbo_tax_code_upsert_failed",
                tenant_id=str(tenant_id),
                tax_code_id=code_id,
                error=str(exc),
            )

    for row in (
        await db.execute(
            select(QboTaxCode).where(
                QboTaxCode.tenant_id == tenant_id,
                QboTaxCode.realm_id == realm_id,
                QboTaxCode.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.qbo_tax_code_id not in seen:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            counters.deactivated += 1

    integration.last_successful_sync_at = now
    await db.flush()
    return counters


def _applicable_on(report_type: str) -> str:
    sales = {"SALES", "GST_FREE_SALES", "EXEMPT_INCOME"}
    return "Sales" if (report_type or "").strip().upper() in sales else "Purchase"


async def _tax_agency_id(client: QboApiClient) -> str:
    agencies = await _query_all(client, "TaxAgency")
    for row in agencies:
        agency_id = str(row.get("Id") or "").strip()
        if agency_id:
            return agency_id
    raise QboApiError(
        400,
        "QuickBooks has no tax agency. Create a tax agency in QuickBooks, then add the tax code here.",
    )


async def create_tax_code_in_qbo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    display_name: str,
    report_type: str,
    components: list[TaxRateComponent],
) -> None:
    name = display_name.strip()
    if not name:
        raise QboApiError(400, "Tax code name is required")
    if not components:
        raise QboApiError(400, "At least one tax rate component is required")
    _, realm_id = await require_qbo_ready(db, tenant_id)
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    agency_id = await _tax_agency_id(client)
    applicable = _applicable_on(report_type)
    details = []
    for index, component in enumerate(components):
        rate_name = (component.name or name).strip()[:100] or name
        if index and rate_name.lower() == name.lower():
            rate_name = f"{rate_name} {index + 1}"
        details.append(
            {
                "TaxRateName": rate_name,
                "RateValue": str(component.rate),
                "TaxAgencyId": agency_id,
                "TaxApplicableOn": applicable,
            }
        )
    body = {"TaxCode": name[:100], "TaxRateDetails": details}
    await client.post_entity("taxservice/taxcode", body)
    await sync_tax_codes_from_qbo(db, tenant_id)
