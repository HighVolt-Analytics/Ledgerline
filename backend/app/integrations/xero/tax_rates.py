"""Xero tax rates: sync (read), create, and delete for Settings."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.client import XeroApiClient, XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.integrations.xero.sync_counts import EntitySyncCounters, payload_hash
from app.models.xero_tax_rate import SOURCE_SYSTEM_XERO, XeroTaxRate
from app.schemas.tax_rates import TaxRateComponent, TaxRateEntry, TaxRateReportType
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"
_CUSTOM_TAX_TYPE = re.compile(r"^TAX\d+$", re.IGNORECASE)

# Settings dropdown → Xero AU/NZ/UK ReportTaxType on create.
REPORT_TYPE_TO_XERO: dict[TaxRateReportType, str] = {
    "SALES": "OUTPUT",
    "PURCHASES": "INPUT",
    "GST_FREE_SALES": "EXEMPTOUTPUT",
    "EXEMPT_INCOME": "EXEMPTOUTPUT",
    "BAS_EXCLUDED": "BASEXCLUDED",
    "GST_FREE_EXPENSES": "EXEMPTEXPENSES",
}

XERO_REPORT_TO_OURS: dict[str, TaxRateReportType] = {
    "OUTPUT": "SALES",
    "OUTPUT2": "SALES",
    "INPUT": "PURCHASES",
    "INPUT2": "PURCHASES",
    "EXEMPTOUTPUT": "GST_FREE_SALES",
    "EXEMPTEXPENSES": "GST_FREE_EXPENSES",
    "BASEXCLUDED": "BAS_EXCLUDED",
    "INPUTTAXED": "EXEMPT_INCOME",
    "NONE": "EXEMPT_INCOME",
}


class XeroTaxRateWriteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def is_system_tax_type(tax_type: str) -> bool:
    """Xero assigns TAX001+ to user-created rates; named codes are org defaults."""
    return not bool(_CUSTOM_TAX_TYPE.fullmatch((tax_type or "").strip()))


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def map_report_tax_type(report_tax_type: str | None, *, fallback: str = "SALES") -> str:
    key = (report_tax_type or "").strip().upper()
    if not key:
        return fallback
    return XERO_REPORT_TO_OURS.get(key, key)


def components_from_payload(payload: dict[str, Any], *, fallback_name: str, fallback_rate: float) -> list[TaxRateComponent]:
    rows: list[TaxRateComponent] = []
    for item in payload.get("TaxComponents") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip() or fallback_name
        try:
            rate = float(item.get("Rate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        rows.append(TaxRateComponent(name=name[:50], rate=rate))
    if rows:
        return rows
    return [TaxRateComponent(name=fallback_name[:50] or "Tax", rate=max(fallback_rate, 0.0))]


def tax_rate_row_to_entry(row: XeroTaxRate) -> TaxRateEntry:
    payload = _parse_payload(row.raw_payload_json)
    name = (row.name or row.tax_type or "Tax").strip()
    rate = float(row.effective_rate or row.display_tax_rate or 0)
    report = str(payload.get("ReportTaxType") or "").strip()
    status = (row.status or "ACTIVE").upper()
    return TaxRateEntry(
        id=row.tax_type,
        display_name=name[:50] or row.tax_type,
        tax_type=map_report_tax_type(report, fallback="SALES"),
        components=components_from_payload(payload, fallback_name=name, fallback_rate=rate),
        can_delete=not is_system_tax_type(row.tax_type) and status == "ACTIVE",
        can_edit=not is_system_tax_type(row.tax_type) and status == "ACTIVE",
        xero_tax_type=row.tax_type,
        status=row.status,
        source="xero",
    )


async def upsert_tax_rate_from_xero_payload(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    xero_tenant_id: str,
    tax: dict[str, Any],
    now: datetime | None = None,
) -> Literal["created", "updated", "unchanged", "skipped"]:
    tax_type = str(tax.get("TaxType") or "").strip()
    if not tax_type:
        return "skipped"
    stamp = now or _now()
    hash_value = payload_hash(tax)
    existing = (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.tax_type == tax_type,
            )
        )
    ).scalar_one_or_none()
    fields = {
        "name": str(tax.get("Name") or tax_type)[:255] or None,
        "status": str(tax.get("Status") or "")[:32] or None,
        "effective_rate": _decimal(tax.get("EffectiveRate")),
        "display_tax_rate": _decimal(tax.get("DisplayTaxRate")),
        "can_apply_to_assets": bool(tax["CanApplyToAssets"]) if "CanApplyToAssets" in tax else None,
        "can_apply_to_equity": bool(tax["CanApplyToEquity"]) if "CanApplyToEquity" in tax else None,
        "can_apply_to_expenses": bool(tax["CanApplyToExpenses"]) if "CanApplyToExpenses" in tax else None,
        "can_apply_to_liabilities": bool(tax["CanApplyToLiabilities"])
        if "CanApplyToLiabilities" in tax
        else None,
        "can_apply_to_revenue": bool(tax["CanApplyToRevenue"]) if "CanApplyToRevenue" in tax else None,
    }
    if existing is None:
        db.add(
            XeroTaxRate(
                tenant_id=tenant_id,
                accounting_integration_id=integration_id,
                xero_tenant_id=xero_tenant_id,
                tax_type=tax_type,
                source_system=SOURCE_SYSTEM_XERO,
                sync_status=_SYNC_ACTIVE,
                payload_hash=hash_value,
                raw_payload_json=json.dumps(tax, default=str),
                last_seen_at=stamp,
                last_synced_at=stamp,
                **fields,
            )
        )
        return "created"
    if existing.payload_hash == hash_value and existing.sync_status == _SYNC_ACTIVE:
        existing.last_seen_at = stamp
        existing.last_synced_at = stamp
        return "unchanged"
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.sync_status = _SYNC_ACTIVE
    existing.payload_hash = hash_value
    existing.raw_payload_json = json.dumps(tax, default=str)
    existing.last_seen_at = stamp
    existing.last_synced_at = stamp
    return "updated"


async def list_synced_tax_rates(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
) -> list[TaxRateEntry]:
    rows = (
        await db.execute(
            select(XeroTaxRate)
            .where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.sync_status == _SYNC_ACTIVE,
            )
            .order_by(XeroTaxRate.name, XeroTaxRate.tax_type)
        )
    ).scalars().all()
    entries: list[TaxRateEntry] = []
    for row in rows:
        status = (row.status or "ACTIVE").upper()
        if status in {"DELETED", "ARCHIVED"}:
            continue
        entries.append(tax_rate_row_to_entry(row))
    return entries


async def sync_tax_rates_from_xero(db: AsyncSession, tenant_id: uuid.UUID) -> EntitySyncCounters:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    payload = await client.get_json("TaxRates")
    counters = EntitySyncCounters()
    now = _now()
    seen: set[str] = set()
    for tax in payload.get("TaxRates") or []:
        if not isinstance(tax, dict):
            continue
        tax_type = str(tax.get("TaxType") or "").strip()
        if not tax_type:
            continue
        counters.fetched += 1
        seen.add(tax_type)
        try:
            outcome = await upsert_tax_rate_from_xero_payload(
                db,
                tenant_id=tenant_id,
                integration_id=integration.id,
                xero_tenant_id=xero_tenant_id,
                tax=tax,
                now=now,
            )
        except Exception as exc:
            counters.failed += 1
            logger.warning(
                "xero_tax_rate_upsert_failed",
                tenant_id=str(tenant_id),
                tax_type=tax_type,
                error=str(exc),
            )
            continue
        if outcome == "created":
            counters.created += 1
        elif outcome == "updated":
            counters.updated += 1
        elif outcome == "unchanged":
            counters.unchanged += 1
    for row in (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.tax_type not in seen:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            counters.deactivated += 1
    await db.flush()
    return counters


async def create_tax_rate_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    display_name: str,
    report_type: TaxRateReportType,
    components: list[TaxRateComponent],
) -> TaxRateEntry:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body = {
        "TaxRates": [
            {
                "Name": display_name,
                "ReportTaxType": REPORT_TYPE_TO_XERO[report_type],
                "TaxComponents": [
                    {"Name": item.name, "Rate": item.rate, "IsCompound": False}
                    for item in components
                ],
            }
        ]
    }
    try:
        payload = await client.put_json("TaxRates", json_body=body)
    except XeroApiError as exc:
        raise XeroTaxRateWriteError(
            exc.message or "Xero rejected the tax rate",
            status_code=exc.status_code or 502,
        ) from exc
    created = next(
        (row for row in (payload.get("TaxRates") or []) if isinstance(row, dict)),
        None,
    )
    if created is None:
        raise XeroTaxRateWriteError("Xero did not return the created tax rate", status_code=502)
    await upsert_tax_rate_from_xero_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        xero_tenant_id=xero_tenant_id,
        tax=created,
    )
    await db.flush()
    tax_type = str(created.get("TaxType") or "").strip()
    row = (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.tax_type == tax_type,
            )
        )
    ).scalar_one()
    return tax_rate_row_to_entry(row)


def _tax_components_payload(components: list[TaxRateComponent]) -> list[dict[str, Any]]:
    return [{"Name": item.name, "Rate": item.rate, "IsCompound": False} for item in components]


async def update_tax_rate_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tax_type: str,
    *,
    display_name: str,
    report_type: TaxRateReportType,
    components: list[TaxRateComponent],
) -> TaxRateEntry:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    cleaned = tax_type.strip()
    if not cleaned:
        raise XeroTaxRateWriteError("Tax rate is required")
    if is_system_tax_type(cleaned):
        raise XeroTaxRateWriteError(
            "This is a default Xero tax rate and cannot be edited."
        )
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body = {
        "TaxRates": [
            {
                "TaxType": cleaned,
                "Name": display_name,
                "ReportTaxType": REPORT_TYPE_TO_XERO[report_type],
                "TaxComponents": _tax_components_payload(components),
            }
        ]
    }
    try:
        payload = await client.put_json("TaxRates", json_body=body)
    except XeroApiError as first:
        body["TaxRates"][0].pop("ReportTaxType", None)
        try:
            payload = await client.put_json("TaxRates", json_body=body)
        except XeroApiError as exc:
            raise XeroTaxRateWriteError(
                exc.message or first.message or "Xero rejected the tax rate update",
                status_code=exc.status_code or 502,
            ) from exc
    updated = next(
        (row for row in (payload.get("TaxRates") or []) if isinstance(row, dict)),
        None,
    )
    if updated is None:
        updated = {
            "TaxType": cleaned,
            "Name": display_name,
            "ReportTaxType": REPORT_TYPE_TO_XERO[report_type],
            "Status": "ACTIVE",
            "TaxComponents": _tax_components_payload(components),
        }
    await upsert_tax_rate_from_xero_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        xero_tenant_id=xero_tenant_id,
        tax=updated,
    )
    await db.flush()
    row = (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.tax_type == str(updated.get("TaxType") or cleaned),
            )
        )
    ).scalar_one()
    return tax_rate_row_to_entry(row)


async def delete_tax_rate_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tax_type: str,
) -> None:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    cleaned = tax_type.strip()
    if not cleaned:
        raise XeroTaxRateWriteError("Tax rate is required")
    if is_system_tax_type(cleaned):
        raise XeroTaxRateWriteError(
            "This is a default Xero tax rate and cannot be deleted."
        )
    row = (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.tax_type == cleaned,
            )
        )
    ).scalar_one_or_none()
    if row is not None and is_system_tax_type(row.tax_type):
        raise XeroTaxRateWriteError(
            "This is a default Xero tax rate and cannot be deleted."
        )
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    try:
        await client.put_json(
            "TaxRates",
            json_body={"TaxRates": [{"TaxType": cleaned, "Status": "DELETED"}]},
        )
    except XeroApiError as exc:
        raise XeroTaxRateWriteError(
            exc.message or "Xero could not delete this tax rate",
            status_code=exc.status_code or 502,
        ) from exc
    now = _now()
    if row is None:
        return
    row.status = "DELETED"
    row.sync_status = _SYNC_INACTIVE
    row.last_synced_at = now
    await db.flush()
