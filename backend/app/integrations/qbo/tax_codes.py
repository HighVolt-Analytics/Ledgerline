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
_MAX_PAGES = 50
_RATE_QUANT = Decimal("0.01")


class QboTaxCodeWriteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


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
        if start > _PAGE_SIZE * _MAX_PAGES:
            break
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
) -> QboTaxCode:
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
    try:
        await client.post_entity("taxservice/taxcode", body)
    except QboApiError as exc:
        raise QboTaxCodeWriteError(
            exc.message or "QuickBooks rejected the tax code",
            status_code=exc.status_code or 502,
        ) from exc
    await sync_tax_codes_from_qbo(db, tenant_id)
    created = await _find_tax_code_after_create(
        db, tenant_id, realm_id, name=name, applicable=applicable
    )
    if created is None:
        raise QboTaxCodeWriteError(
            "QuickBooks created a tax code but it could not be loaded",
            status_code=502,
        )
    return created


def quantize_tax_percent(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_RATE_QUANT)


def invoice_gst_percent(invoice: Any) -> Decimal | None:
    """Purchase tax % from gst_rate, or 0% when GST amount is zero."""
    rate = _decimal(getattr(invoice, "gst_rate", None))
    if rate is not None:
        return quantize_tax_percent(rate)
    gst = _decimal(getattr(invoice, "gst", None))
    if gst is not None and gst == 0:
        return Decimal("0.00")
    return None


def format_tax_percent_label(percent: Decimal) -> str:
    quantized = quantize_tax_percent(percent)
    if quantized == quantized.to_integral():
        return str(int(quantized))
    text = format(quantized.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def default_purchase_tax_code_name(percent: Decimal) -> str:
    """Stable auto-create name. Never used to rename an existing QBO tax code."""
    if quantize_tax_percent(percent) == Decimal("0.00"):
        return "GST free 0%"
    return f"GST {format_tax_percent_label(percent)}%"


def unused_tax_code_name(base: str, existing_names: list[str]) -> str:
    taken = {(name or "").strip().lower() for name in existing_names if (name or "").strip()}
    candidate = base.strip()[:100]
    if candidate.lower() not in taken:
        return candidate
    for index in range(2, 50):
        extra = f"{base.strip()} ({index})"[:100]
        if extra.lower() not in taken:
            return extra
    return f"{base.strip()[:90]} {uuid.uuid4().hex[:6]}"


def _name_match_score(name: str | None, *, zero_rate: bool) -> tuple[int, int, int, int]:
    text = (name or "").casefold()
    gst = 1 if "gst" in text else 0
    purchase = 1 if "purchas" in text else 0
    sales = 1 if "sale" in text else 0
    free = 1 if any(
        token in text
        for token in ("free", "exempt", "zero", "out of scope", "non-tax", "nontax", "no gst")
    ) else 0
    if zero_rate:
        return (free, gst, purchase, -sales)
    return (gst, purchase, -sales, -free)


def match_purchase_tax_code(
    rows: list[QboTaxCode],
    gst_percent: Decimal,
) -> QboTaxCode | None:
    """Reuse an active purchase TaxCode with the same %. Never rename."""
    target = quantize_tax_percent(gst_percent)
    zero_rate = target == Decimal("0.00")
    matches: list[QboTaxCode] = []
    for row in rows:
        if not row.active or (row.sync_status or "") != _SYNC_ACTIVE:
            continue
        if row.purchase_rate is None:
            continue
        if quantize_tax_percent(row.purchase_rate) != target:
            continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            _name_match_score(row.name, zero_rate=zero_rate),
            len(row.name or ""),
            row.qbo_tax_code_id or "",
        ),
        reverse=True,
    )
    return matches[0]


async def _list_cached_tax_codes(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
) -> list[QboTaxCode]:
    return list(
        (
            await db.execute(
                select(QboTaxCode).where(
                    QboTaxCode.tenant_id == tenant_id,
                    QboTaxCode.realm_id == realm_id,
                    QboTaxCode.sync_status == _SYNC_ACTIVE,
                )
            )
        ).scalars().all()
    )


async def _find_tax_code_after_create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
    *,
    name: str,
    applicable: str,
) -> QboTaxCode | None:
    rows = await _list_cached_tax_codes(db, tenant_id, realm_id)
    wanted = name.strip().casefold()
    named = [row for row in rows if (row.name or "").strip().casefold() == wanted]
    if applicable == "Purchase":
        named.sort(key=lambda row: (row.purchase_rate is None, row.qbo_tax_code_id or ""))
    else:
        named.sort(key=lambda row: (row.sales_rate is None, row.qbo_tax_code_id or ""))
    return named[0] if named else None


def _tax_code_result(row: QboTaxCode, *, created: bool) -> dict[str, Any]:
    return {
        "created": created,
        "tax_code_id": row.qbo_tax_code_id,
        "name": row.name,
        "purchase_rate": str(row.purchase_rate) if row.purchase_rate is not None else None,
    }


async def ensure_invoice_qbo_tax_code(
    db: AsyncSession,
    invoice: Any,
) -> dict[str, Any] | None:
    """Match a purchase TaxCode by GST %, or create GST 20% / GST free 0% style.

    Existing QBO names are never changed. Missing gst_rate (except GST amount 0) is a no-op.
    """
    percent = invoice_gst_percent(invoice)
    if percent is None:
        return None
    tenant_id = invoice.tenant_id
    _, realm_id = await require_qbo_ready(db, tenant_id)
    rows = await _list_cached_tax_codes(db, tenant_id, realm_id)
    matched = match_purchase_tax_code(rows, percent)
    if matched is not None:
        return _tax_code_result(matched, created=False)

    display_name = unused_tax_code_name(
        default_purchase_tax_code_name(percent),
        [row.name or "" for row in rows],
    )
    component_name = display_name[:50] or "GST"
    try:
        created = await create_tax_code_in_qbo(
            db,
            tenant_id,
            display_name=display_name,
            report_type="PURCHASES",
            components=[TaxRateComponent(name=component_name, rate=float(percent))],
        )
    except QboApiError as exc:
        raise QboTaxCodeWriteError(
            exc.message or "QuickBooks rejected the tax code",
            status_code=exc.status_code or 502,
        ) from exc
    return _tax_code_result(created, created=True)
