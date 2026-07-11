"""Push processed invoices to Xero with idempotent external refs."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.accounting_integration import AccountingProvider
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.invoice import Invoice, InvoiceStatus
from app.services.integration.accounting_integration_service import require_xero_ready
from app.services.integration.xero_client import XeroApiError, XeroClient
from app.services.integration.xero_mapping_validation import (
    XeroMappingValidationError,
    validate_invoice_xero_mappings,
    _normalize_contact_key,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER = AccountingProvider.XERO.value
_ENTITY_TYPE_INVOICE = "invoice"


def _invoice_xero_type(route_target: str | None) -> str:
    if (route_target or "").strip() == ROUTE_SALES:
        return "ACCREC"
    return "ACCPAY"


def _decimal(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


async def _contact_id_for_invoice(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice: Invoice,
) -> str | None:
    contact_name = (invoice.vendor or "").strip()
    if not contact_name:
        return None
    row = (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == _PROVIDER,
                ExternalAccountingRef.entity_type == "contact",
                ExternalAccountingRef.internal_entity_id == _normalize_contact_key(contact_name),
            )
        )
    ).scalar_one_or_none()
    return row.external_entity_id if row else None


def _build_invoice_payload(invoice: Invoice, *, contact_id: str) -> dict[str, Any]:
    xero_type = _invoice_xero_type(invoice.route_target)
    line_items: list[dict[str, Any]] = []
    for item in invoice.line_items:
        line_items.append(
            {
                "Description": item.description or "Line item",
                "Quantity": _decimal(item.qty) or 1.0,
                "UnitAmount": _decimal(item.unit_price) or _decimal(item.amount) or 0.0,
                "LineAmount": _decimal(item.amount),
                "TaxAmount": _decimal(item.tax_amount),
                "AccountCode": invoice.account_code,
            }
        )
    if not line_items:
        line_items.append(
            {
                "Description": invoice.invoice_no or "Invoice total",
                "Quantity": 1.0,
                "UnitAmount": _decimal(invoice.total) or _decimal(invoice.subtotal) or 0.0,
                "AccountCode": invoice.account_code,
            }
        )

    payload: dict[str, Any] = {
        "Type": xero_type,
        "Contact": {"ContactID": contact_id},
        "LineItems": line_items,
        "InvoiceNumber": invoice.invoice_no or invoice.document_ref,
        "CurrencyCode": invoice.currency or "AUD",
        "Status": "DRAFT",
    }
    if invoice.invoice_date:
        payload["Date"] = invoice.invoice_date.isoformat()
    if invoice.due_date:
        payload["DueDate"] = invoice.due_date.isoformat()
    if invoice.po_reference:
        payload["Reference"] = invoice.po_reference
    elif invoice.so_reference:
        payload["Reference"] = invoice.so_reference
    return payload


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _get_invoice_ref(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> ExternalAccountingRef | None:
    return (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == _PROVIDER,
                ExternalAccountingRef.entity_type == _ENTITY_TYPE_INVOICE,
                ExternalAccountingRef.internal_entity_id == str(invoice_id),
            )
        )
    ).scalar_one_or_none()


async def get_invoice_xero_status(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> dict[str, Any]:
    ref = await _get_invoice_ref(db, tenant_id=tenant_id, invoice_id=invoice_id)
    if ref is None:
        return {
            "invoice_id": invoice_id,
            "pushed": False,
            "external_entity_id": None,
            "external_number": None,
            "external_status": None,
            "last_pushed_at": None,
            "last_error_code": None,
            "last_error_message": None,
            "sync_status": None,
        }
    return {
        "invoice_id": invoice_id,
        "pushed": bool(ref.external_entity_id),
        "external_entity_id": ref.external_entity_id,
        "external_number": ref.external_number,
        "external_status": ref.external_status,
        "last_pushed_at": ref.last_pushed_at,
        "last_error_code": ref.last_error_code,
        "last_error_message": ref.last_error_message,
        "payload_hash": ref.payload_hash,
        "sync_status": ref.sync_status,
        "last_synced_at": ref.last_synced_at,
        "sync_error_code": ref.sync_error_code,
        "sync_error_message": ref.sync_error_message,
    }


async def push_invoice_to_xero(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    user_id: int,
) -> dict[str, Any]:
    del user_id  # reserved for audit attribution at API layer
    invoice = (
        await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found")
    if invoice.status != InvoiceStatus.PROCESSED:
        raise ValueError("Invoice must be processed before pushing to Xero")

    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    validation = await validate_invoice_xero_mappings(
        db,
        tenant_id=tenant_id,
        invoice=invoice,
        organisation_id=integration.provider_tenant_id or xero_tenant_id,
    )
    if not validation.valid:
        raise XeroMappingValidationError(validation)

    contact_id = await _contact_id_for_invoice(db, tenant_id=tenant_id, invoice=invoice)
    if not contact_id:
        raise XeroMappingValidationError(validation)

    payload = _build_invoice_payload(invoice, contact_id=contact_id)
    payload_hash = _payload_hash(payload)

    existing = await _get_invoice_ref(db, tenant_id=tenant_id, invoice_id=invoice_id)
    if (
        existing
        and existing.external_entity_id
        and existing.payload_hash == payload_hash
        and not existing.last_error_code
    ):
        return {
            "invoice_id": invoice_id,
            "skipped": True,
            "reason": "already_pushed",
            "external_entity_id": existing.external_entity_id,
            "external_number": existing.external_number,
            "external_status": existing.external_status,
        }

    client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    now = datetime.now(timezone.utc)
    ref = existing
    if ref is None:
        ref = ExternalAccountingRef(
            tenant_id=tenant_id,
            provider=_PROVIDER,
            entity_type=_ENTITY_TYPE_INVOICE,
            internal_entity_id=str(invoice_id),
            external_entity_id="",
        )
        db.add(ref)

    ref.sync_status = "pushing"
    ref.sync_attempts = int(ref.sync_attempts or 0) + 1
    await db.flush()

    try:
        response = await client.post_json("Invoices", json_body={"Invoices": [payload]})
        invoices = response.get("Invoices") or []
        if not invoices:
            raise XeroApiError(
                status_code=500,
                error_code="empty_response",
                message="Xero returned no invoice payload",
            )
        created = invoices[0]
        ref.external_entity_id = str(created.get("InvoiceID") or "")
        ref.external_number = created.get("InvoiceNumber")
        ref.external_status = created.get("Status")
        ref.payload_hash = payload_hash
        ref.last_pushed_at = now
        ref.last_synced_at = now
        ref.last_error_code = None
        ref.last_error_message = None
        ref.sync_status = "synced"
        ref.sync_error_code = None
        ref.sync_error_message = None
        ref.metadata_json = json.dumps(
            {"xero_type": payload["Type"], "route_target": invoice.route_target}
        )
        await db.flush()
        return {
            "invoice_id": invoice_id,
            "skipped": False,
            "external_entity_id": ref.external_entity_id,
            "external_number": ref.external_number,
            "external_status": ref.external_status,
            "xero_type": payload["Type"],
        }
    except XeroApiError as exc:
        ref.payload_hash = payload_hash
        ref.last_error_code = exc.error_code
        ref.last_error_message = exc.message
        ref.sync_status = "failed"
        ref.sync_error_code = exc.error_code
        ref.sync_error_message = exc.message
        await db.flush()
        raise
