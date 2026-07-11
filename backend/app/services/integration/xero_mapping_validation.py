"""Validate invoice mappings before pushing to Xero."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import AccountingProvider
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.invoice import Invoice

_PROVIDER = AccountingProvider.XERO.value


@dataclass
class XeroMappingValidationResult:
    valid: bool
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors}


class XeroMappingValidationError(ValueError):
    def __init__(self, result: XeroMappingValidationResult) -> None:
        self.result = result
        super().__init__("Xero mapping validation failed")


def _normalize_contact_key(name: str) -> str:
    collapsed = re.sub(r"\s+", " ", (name or "").strip().lower())
    return collapsed[:255] or "unknown"


async def _ref_exists(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entity_type: str,
    internal_entity_id: str,
) -> ExternalAccountingRef | None:
    return (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == _PROVIDER,
                ExternalAccountingRef.entity_type == entity_type,
                ExternalAccountingRef.internal_entity_id == internal_entity_id,
            )
        )
    ).scalar_one_or_none()


def _line_has_tax(invoice: Invoice) -> bool:
    for item in invoice.line_items:
        amount = item.tax_amount
        if amount is not None and Decimal(amount) > 0:
            return True
    return False


async def validate_invoice_xero_mappings(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice: Invoice,
    organisation_id: str,
) -> XeroMappingValidationResult:
    errors: list[dict[str, str]] = []

    if not organisation_id.strip():
        errors.append(
            {
                "field": "organisation",
                "code": "missing_organisation",
                "message": "Xero organisation is not selected",
            }
        )
    else:
        org_ref = await _ref_exists(
            db,
            tenant_id=tenant_id,
            entity_type="organisation",
            internal_entity_id=organisation_id,
        )
        if org_ref is None:
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
    else:
        contact_ref = await _ref_exists(
            db,
            tenant_id=tenant_id,
            entity_type="contact",
            internal_entity_id=_normalize_contact_key(contact_name),
        )
        if contact_ref is None or not contact_ref.external_entity_id:
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
    else:
        account_ref = await _ref_exists(
            db,
            tenant_id=tenant_id,
            entity_type="account",
            internal_entity_id=account_code,
        )
        if account_ref is None:
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
    else:
        currency_ref = await _ref_exists(
            db,
            tenant_id=tenant_id,
            entity_type="currency",
            internal_entity_id=currency,
        )
        if currency_ref is None:
            errors.append(
                {
                    "field": "currency",
                    "code": "currency_not_mapped",
                    "message": f"Currency '{currency}' was not found in synced Xero organisation settings",
                }
            )

    if _line_has_tax(invoice):
        tax_refs = (
            await db.execute(
                select(ExternalAccountingRef).where(
                    ExternalAccountingRef.tenant_id == tenant_id,
                    ExternalAccountingRef.provider == _PROVIDER,
                    ExternalAccountingRef.entity_type == "tax_rate",
                )
            )
        ).scalars().all()
        if not tax_refs:
            errors.append(
                {
                    "field": "tax_type",
                    "code": "tax_type_not_mapped",
                    "message": "Line items include tax but no Xero tax rates are synced",
                }
            )

    return XeroMappingValidationResult(valid=not errors, errors=errors)
