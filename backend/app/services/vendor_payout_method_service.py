"""Read-only vendor payout method tracking (no money movement)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stripe_payments import VendorPaymentMethod
from app.models.vendor import VendorRegistry
from app.schemas.vendor import (
    VendorPayoutMethodCreate,
    VendorPayoutMethodResponse,
    VendorPayoutMethodUpdate,
)

PAYOUT_METHOD_TYPES = frozenset(
    {
        "manual_bank",
        "stripe_connected_account",
        "external_bank_phase2",
        "stripe_global_payouts",
        "stripe_treasury",
        "external_ap_provider",
    }
)
PAYOUT_METHOD_STATUSES = frozenset(
    {
        "not_configured",
        "pending",
        "verified",
        "disabled",
    }
)

_LAST4_RE = re.compile(r"^\d{0,4}$")
_STRIPE_ACCOUNT_ID_RE = re.compile(r"^acct_[A-Za-z0-9]+$")


class VendorPayoutMethodError(ValueError):
    """Validation error for payout method payloads."""


def _normalize_vendor_key(name: str | None) -> str:
    return (name or "").strip().lower()


NOT_CONFIGURED_PAYOUT_SUMMARY: dict[str, str | None] = {
    "status": "not_configured",
    "method_type": None,
}


def _summarize_methods_by_vendor(
    methods: list[VendorPaymentMethod],
) -> dict[int, dict[str, str | None]]:
    by_vendor: dict[int, list[VendorPaymentMethod]] = {}
    for method in methods:
        by_vendor.setdefault(method.vendor_id, []).append(method)

    summaries: dict[int, dict[str, str | None]] = {}
    for vendor_id, rows in by_vendor.items():
        active = [row for row in rows if (row.status or "") != "disabled"]
        default = next((row for row in active if row.is_default), None)
        if default is None and active:
            default = active[0]
        if default is None:
            summaries[vendor_id] = dict(NOT_CONFIGURED_PAYOUT_SUMMARY)
        else:
            summaries[vendor_id] = {
                "status": default.status or "not_configured",
                "method_type": default.method_type,
            }
    return summaries


def _validate_last4(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    cleaned = value.strip()
    if not _LAST4_RE.fullmatch(cleaned):
        raise VendorPayoutMethodError("last4 must be up to 4 digits")
    return cleaned or None


def _validate_stripe_account_id(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    cleaned = value.strip()
    if not _STRIPE_ACCOUNT_ID_RE.fullmatch(cleaned):
        raise VendorPayoutMethodError("stripe_account_id must be a Stripe account id (acct_…)")
    return cleaned


def _provider_metadata(row: VendorPaymentMethod) -> dict[str, str | None]:
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    method_type = row.method_type or "manual_bank"
    provider = str(raw.get("provider") or method_type)
    if method_type == "stripe_global_payouts":
        provider = "stripe_global_payouts"
    elif method_type == "stripe_treasury":
        provider = "stripe_treasury"
    elif method_type == "external_ap_provider":
        provider = "external_ap_provider"
    elif method_type == "manual_bank":
        provider = "manual_bank"
    recipient_status = str(raw.get("recipient_status") or row.status or "pending")
    if method_type == "stripe_global_payouts" and recipient_status == "verified":
        recipient_status = "pending"
    return {
        "provider": provider,
        "provider_recipient_id": raw.get("provider_recipient_id"),
        "recipient_status": recipient_status,
        "recipient_country": raw.get("recipient_country"),
        "recipient_currency": raw.get("recipient_currency") or row.currency,
    }


def payout_method_to_response(row: VendorPaymentMethod) -> VendorPayoutMethodResponse:
    meta = _provider_metadata(row)
    return VendorPayoutMethodResponse(
        id=row.id,
        vendor_id=row.vendor_id,
        method_type=row.method_type or "manual_bank",
        display_label=row.display_label,
        stripe_account_id=row.stripe_account_id,
        last4=row.last4,
        currency=row.currency or "AUD",
        status=row.status or "not_configured",
        is_default=bool(row.is_default),
        provider=meta["provider"],
        provider_recipient_id=meta["provider_recipient_id"],
        recipient_status=meta["recipient_status"],
        recipient_country=meta["recipient_country"],
        recipient_currency=meta["recipient_currency"],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _require_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
) -> VendorRegistry:
    row = await db.get(VendorRegistry, vendor_id)
    if row is None or row.tenant_id != tenant_id:
        raise LookupError("Vendor not found")
    return row


async def _require_method(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
    method_id: int,
) -> VendorPaymentMethod:
    row = await db.get(VendorPaymentMethod, method_id)
    if row is None or row.tenant_id != tenant_id or row.vendor_id != vendor_id:
        raise LookupError("Payout method not found")
    return row


async def _clear_other_defaults(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
    *,
    except_method_id: int | None = None,
) -> None:
    stmt = (
        update(VendorPaymentMethod)
        .where(
            VendorPaymentMethod.tenant_id == tenant_id,
            VendorPaymentMethod.vendor_id == vendor_id,
            VendorPaymentMethod.is_default.is_(True),
        )
        .values(is_default=False)
    )
    if except_method_id is not None:
        stmt = stmt.where(VendorPaymentMethod.id != except_method_id)
    await db.execute(stmt)


async def list_payout_methods_for_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
) -> list[VendorPayoutMethodResponse]:
    await _require_vendor(db, tenant_id, vendor_id)
    rows = (
        await db.execute(
            select(VendorPaymentMethod)
            .where(
                VendorPaymentMethod.tenant_id == tenant_id,
                VendorPaymentMethod.vendor_id == vendor_id,
            )
            .order_by(
                VendorPaymentMethod.is_default.desc(),
                VendorPaymentMethod.updated_at.desc(),
            )
        )
    ).scalars().all()
    return [payout_method_to_response(row) for row in rows]


async def create_payout_method_for_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
    body: VendorPayoutMethodCreate,
) -> VendorPayoutMethodResponse:
    await _require_vendor(db, tenant_id, vendor_id)

    if body.method_type not in PAYOUT_METHOD_TYPES:
        raise VendorPayoutMethodError(f"Unsupported method_type: {body.method_type}")
    if body.status not in PAYOUT_METHOD_STATUSES:
        raise VendorPayoutMethodError(f"Unsupported status: {body.status}")

    last4 = _validate_last4(body.last4)
    stripe_account_id = _validate_stripe_account_id(body.stripe_account_id)
    if body.method_type == "stripe_connected_account" and not stripe_account_id:
        raise VendorPayoutMethodError(
            "stripe_account_id is required for stripe_connected_account methods"
        )

    is_default = body.is_default
    if is_default:
        await _clear_other_defaults(db, tenant_id, vendor_id)

    row = VendorPaymentMethod(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        method_type=body.method_type,
        display_label=(body.display_label or "").strip() or None,
        stripe_account_id=stripe_account_id,
        last4=last4,
        currency=(body.currency or "AUD").upper()[:3],
        status=body.status,
        is_default=is_default,
    )
    db.add(row)
    await db.flush()
    return payout_method_to_response(row)


async def update_payout_method_for_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
    method_id: int,
    body: VendorPayoutMethodUpdate,
) -> VendorPayoutMethodResponse:
    row = await _require_method(db, tenant_id, vendor_id, method_id)

    if body.method_type is not None:
        if body.method_type not in PAYOUT_METHOD_TYPES:
            raise VendorPayoutMethodError(f"Unsupported method_type: {body.method_type}")
        row.method_type = body.method_type
    if body.display_label is not None:
        row.display_label = body.display_label.strip() or None
    if body.stripe_account_id is not None:
        row.stripe_account_id = _validate_stripe_account_id(body.stripe_account_id)
    if body.last4 is not None:
        row.last4 = _validate_last4(body.last4)
    if body.currency is not None:
        row.currency = body.currency.upper()[:3]
    if body.status is not None:
        if body.status not in PAYOUT_METHOD_STATUSES:
            raise VendorPayoutMethodError(f"Unsupported status: {body.status}")
        row.status = body.status
    if body.is_default is not None:
        if body.is_default:
            await _clear_other_defaults(
                db, tenant_id, vendor_id, except_method_id=row.id
            )
        row.is_default = body.is_default

    method_type = row.method_type or ""
    if method_type == "stripe_connected_account" and not row.stripe_account_id:
        raise VendorPayoutMethodError(
            "stripe_account_id is required for stripe_connected_account methods"
        )

    await db.flush()
    return payout_method_to_response(row)


async def delete_payout_method_for_vendor(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_id: int,
    method_id: int,
) -> None:
    row = await _require_method(db, tenant_id, vendor_id, method_id)
    await db.delete(row)
    await db.flush()


async def resolve_vendor_registry_id_for_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    vendor_name: str | None,
    storage_vendor_slug: str | None,
) -> int | None:
    """Resolve vendor_registry.id from invoice slug (exact) then vendor name (exact)."""
    slug = (storage_vendor_slug or "").strip()
    if slug and slug != "unknown":
        matched_id = (
            await db.execute(
                select(VendorRegistry.id).where(
                    VendorRegistry.tenant_id == tenant_id,
                    VendorRegistry.vendor_slug == slug,
                )
            )
        ).scalar_one_or_none()
        if matched_id is not None:
            return int(matched_id)

    name_key = _normalize_vendor_key(vendor_name)
    if not name_key:
        return None

    vendors = (
        await db.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == tenant_id)
        )
    ).scalars().all()
    for vendor in vendors:
        if _normalize_vendor_key(vendor.vendor_name) == name_key:
            return vendor.id
    return None


async def default_payout_lookup_by_vendor_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_registry_ids: list[int | None],
) -> dict[int, dict[str, str | None]]:
    """Map vendor_registry.id -> default payout method summary."""
    vendor_ids = {vendor_id for vendor_id in vendor_registry_ids if vendor_id is not None}
    if not vendor_ids:
        return {}

    methods = (
        await db.execute(
            select(VendorPaymentMethod).where(
                VendorPaymentMethod.tenant_id == tenant_id,
                VendorPaymentMethod.vendor_id.in_(vendor_ids),
            )
        )
    ).scalars().all()
    return _summarize_methods_by_vendor(methods)


async def default_payout_lookup_by_vendor_names(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_names: list[str | None],
) -> dict[str, dict[str, str | None]]:
    """Map normalized vendor name -> default payout method summary."""
    names = {_normalize_vendor_key(name) for name in vendor_names if _normalize_vendor_key(name)}
    if not names:
        return {}

    vendors = (
        await db.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == tenant_id)
        )
    ).scalars().all()

    name_to_vendor_id: dict[str, int] = {}
    for vendor in vendors:
        keys = {
            _normalize_vendor_key(vendor.vendor_name),
            _normalize_vendor_key(vendor.vendor_slug.replace("-", " ")),
            _normalize_vendor_key(vendor.vendor_slug),
        }
        for key in keys:
            if key:
                name_to_vendor_id[key] = vendor.id

    vendor_ids: set[int] = set()
    payment_name_to_vendor_id: dict[str, int] = {}
    for name in names:
        vendor_id = name_to_vendor_id.get(name)
        if vendor_id is None:
            for key, vid in name_to_vendor_id.items():
                if name in key or key in name:
                    vendor_id = vid
                    break
        if vendor_id is not None:
            vendor_ids.add(vendor_id)
            payment_name_to_vendor_id[name] = vendor_id

    if not vendor_ids:
        return {}

    methods = (
        await db.execute(
            select(VendorPaymentMethod).where(
                VendorPaymentMethod.tenant_id == tenant_id,
                VendorPaymentMethod.vendor_id.in_(vendor_ids),
            )
        )
    ).scalars().all()

    vendor_id_to_summary = _summarize_methods_by_vendor(methods)

    result: dict[str, dict[str, str | None]] = {}
    for name, vendor_id in payment_name_to_vendor_id.items():
        result[name] = vendor_id_to_summary.get(vendor_id, dict(NOT_CONFIGURED_PAYOUT_SUMMARY))
    return result


async def payout_summary_for_payments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payments: list[Any],
) -> list[dict[str, str | None]]:
    """Resolve payout summaries for payments: FK first, name fallback for legacy rows."""
    from app.models.payment import Payment

    payment_rows = [payment for payment in payments if isinstance(payment, Payment)]
    if not payment_rows:
        return []

    id_lookup = await default_payout_lookup_by_vendor_ids(
        db,
        tenant_id,
        [payment.vendor_registry_id for payment in payment_rows],
    )

    fallback_names = [
        payment.vendor
        for payment in payment_rows
        if payment.vendor_registry_id is None and payment.vendor
    ]
    name_lookup = await default_payout_lookup_by_vendor_names(db, tenant_id, fallback_names)

    summaries: list[dict[str, str | None]] = []
    for payment in payment_rows:
        if payment.vendor_registry_id is not None:
            summary = id_lookup.get(
                payment.vendor_registry_id,
                dict(NOT_CONFIGURED_PAYOUT_SUMMARY),
            )
        else:
            key = _normalize_vendor_key(payment.vendor)
            if not key:
                summary = {}
            else:
                summary = name_lookup.get(key, dict(NOT_CONFIGURED_PAYOUT_SUMMARY))
        summaries.append(summary)
    return summaries
