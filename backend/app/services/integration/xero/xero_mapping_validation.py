"""Validate invoice mappings before pushing to Xero."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_tax_rate import XeroTaxRate


@dataclass
class XeroMappingValidationResult:
    valid: bool
    errors: list[dict[str, str]] = field(default_factory=list)
    contact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors}


class XeroMappingValidationError(ValueError):
    def __init__(self, result: XeroMappingValidationResult) -> None:
        self.result = result
        super().__init__("Xero mapping validation failed")


def _normalize_contact_key(name: str) -> str:
    collapsed = re.sub(r"\s+", " ", (name or "").strip().lower())
    return collapsed[:255] or "unknown"


async def _ensure_line_items_loaded(db: AsyncSession, invoice: Invoice) -> None:
    """Load line_items eagerly so async sessions never lazy-load outside a greenlet."""
    if invoice.id is None:
        return
    state = sa_inspect(invoice)
    if "line_items" not in state.unloaded:
        return
    loaded = (
        await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == invoice.id, Invoice.tenant_id == invoice.tenant_id)
        )
    ).scalar_one_or_none()
    if loaded is not None:
        invoice.line_items = list(loaded.line_items)


def _line_has_tax(invoice: Invoice) -> bool:
    items = invoice.__dict__.get("line_items")
    if items is None:
        return False
    for item in items:
        amount = item.tax_amount
        if amount is not None and Decimal(amount) > 0:
            return True
    return False


async def find_xero_contact_id(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
    vendor_name: str,
) -> str | None:
    key = _normalize_contact_key(vendor_name)
    rows = (
        await db.execute(
            select(XeroContact).where(
                XeroContact.tenant_id == tenant_id,
                XeroContact.xero_tenant_id == xero_tenant_id,
                XeroContact.sync_status == "active",
            )
        )
    ).scalars().all()
    for row in rows:
        if _normalize_contact_key(row.name or "") == key:
            return row.xero_contact_id
    return None


async def validate_invoice_xero_mappings(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice: Invoice,
    organisation_id: str,
) -> XeroMappingValidationResult:
    errors: list[dict[str, str]] = []
    contact_id: str | None = None
    xero_tenant_id = organisation_id.strip()
    await _ensure_line_items_loaded(db, invoice)

    if not xero_tenant_id:
        errors.append(
            {
                "field": "organisation",
                "code": "missing_organisation",
                "message": "Xero organisation is not selected",
            }
        )
    else:
        account_count = (
            await db.execute(
                select(func.count()).select_from(XeroAccount).where(
                    XeroAccount.tenant_id == tenant_id,
                    XeroAccount.xero_tenant_id == xero_tenant_id,
                    XeroAccount.sync_status == "active",
                )
            )
        ).scalar_one()
        if int(account_count or 0) == 0:
            errors.append(
                {
                    "field": "organisation",
                    "code": "organisation_not_synced",
                    "message": "Sync Xero settings before pushing invoices",
                }
            )

    contact_name = (invoice.vendor or "").strip()
    if not contact_name:
        errors.append(
            {
                "field": "contact",
                "code": "missing_contact",
                "message": "Invoice vendor is required for Xero ContactID mapping",
            }
        )
    elif xero_tenant_id:
        contact_id = await find_xero_contact_id(
            db,
            tenant_id=tenant_id,
            xero_tenant_id=xero_tenant_id,
            vendor_name=contact_name,
        )
        if not contact_id:
            errors.append(
                {
                    "field": "contact",
                    "code": "contact_not_mapped",
                    "message": f"No synced Xero contact for vendor '{contact_name}'",
                }
            )

    account_code = (invoice.account_code or "").strip()
    if not account_code:
        errors.append(
            {
                "field": "account_code",
                "code": "missing_account_code",
                "message": "Invoice account code is required",
            }
        )
    elif xero_tenant_id:
        account = (
            await db.execute(
                select(XeroAccount).where(
                    XeroAccount.tenant_id == tenant_id,
                    XeroAccount.xero_tenant_id == xero_tenant_id,
                    XeroAccount.code == account_code,
                    XeroAccount.sync_status == "active",
                )
            )
        ).scalar_one_or_none()
        if account is None:
            errors.append(
                {
                    "field": "account_code",
                    "code": "account_not_mapped",
                    "message": f"Account code '{account_code}' was not found in synced Xero accounts",
                }
            )

    currency = (invoice.currency or "").strip().upper()
    if not currency:
        errors.append(
            {
                "field": "currency",
                "code": "missing_currency",
                "message": "Invoice currency is required",
            }
        )
    elif xero_tenant_id:
        currency_row = (
            await db.execute(
                select(XeroCurrency).where(
                    XeroCurrency.tenant_id == tenant_id,
                    XeroCurrency.xero_tenant_id == xero_tenant_id,
                    XeroCurrency.code == currency,
                    XeroCurrency.sync_status == "active",
                )
            )
        ).scalar_one_or_none()
        if currency_row is None:
            errors.append(
                {
                    "field": "currency",
                    "code": "currency_not_mapped",
                    "message": f"Currency '{currency}' was not found in synced Xero organisation settings",
                }
            )

    if _line_has_tax(invoice) and xero_tenant_id:
        tax_count = (
            await db.execute(
                select(func.count()).select_from(XeroTaxRate).where(
                    XeroTaxRate.tenant_id == tenant_id,
                    XeroTaxRate.xero_tenant_id == xero_tenant_id,
                    XeroTaxRate.sync_status == "active",
                )
            )
        ).scalar_one()
        if int(tax_count or 0) == 0:
            errors.append(
                {
                    "field": "tax_type",
                    "code": "tax_type_not_mapped",
                    "message": "Line items include tax but no Xero tax rates are synced",
                }
            )

    return XeroMappingValidationResult(
        valid=not errors,
        errors=errors,
        contact_id=contact_id,
    )
