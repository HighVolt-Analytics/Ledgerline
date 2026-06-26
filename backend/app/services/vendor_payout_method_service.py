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


def payout_method_to_response(row: VendorPaymentMethod) -> VendorPayoutMethodResponse:
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

    by_vendor: dict[int, list[VendorPaymentMethod]] = {}
    for method in methods:
        by_vendor.setdefault(method.vendor_id, []).append(method)

    vendor_id_to_summary: dict[int, dict[str, str | None]] = {}
    for vendor_id, rows in by_vendor.items():
        active = [r for r in rows if (r.status or "") != "disabled"]
        default = next((r for r in active if r.is_default), None)
        if default is None and active:
            default = active[0]
        if default is None:
            vendor_id_to_summary[vendor_id] = {
                "status": "not_configured",
                "method_type": None,
            }
        else:
            vendor_id_to_summary[vendor_id] = {
                "status": default.status or "not_configured",
                "method_type": default.method_type,
            }

    result: dict[str, dict[str, str | None]] = {}
    for name, vendor_id in payment_name_to_vendor_id.items():
        result[name] = vendor_id_to_summary.get(
            vendor_id,
            {"status": "not_configured", "method_type": None},
        )
    return result
