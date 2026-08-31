"""Push processed invoices to Xero via the new Integrations export pipeline."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.export import (
    XeroExportError,
    get_export_ledger,
    ledger_to_dict,
    list_export_ledger,
    push_invoice_to_xero_pipeline,
)
from app.integrations.xero.mapping import (
    XeroMappingValidationError,
    XeroMappingValidationResult,
)


async def get_invoice_xero_status(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> dict[str, Any]:
    from app.models.accounting_export_ledger import AccountingExportLedger, PROVIDER_XERO
    from app.models.external_accounting_ref import ExternalAccountingRef

    ledger = (
        await db.execute(
            select(AccountingExportLedger)
            .where(
                AccountingExportLedger.tenant_id == tenant_id,
                AccountingExportLedger.provider == PROVIDER_XERO,
                AccountingExportLedger.source_invoice_id == invoice_id,
            )
            .order_by(AccountingExportLedger.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if ledger is not None:
        evidence = ledger_to_dict(ledger)
        return {
            "invoice_id": invoice_id,
            "pushed": bool(ledger.external_id),
            "external_entity_id": ledger.external_id,
            "external_number": ledger.external_number,
            "external_status": ledger.external_status,
            "sync_id": ledger.id,
            "attachment_status": ledger.attachment_status,
            "export_complete": evidence.get("export_complete"),
            "status": ledger.status,
            "error_bucket": ledger.error_bucket,
            "error_code": ledger.error_code,
            "error_message": ledger.error_message,
            "payload_hash": ledger.payload_hash,
            "last_pushed_at": ledger.last_attempt_at,
            "sync_status": ledger.status,
        }

    ref = (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == PROVIDER_XERO,
                ExternalAccountingRef.entity_type == "invoice",
                ExternalAccountingRef.internal_entity_id == str(invoice_id),
            )
        )
    ).scalar_one_or_none()
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
    }


async def push_invoice_to_xero(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
    user_id: int,
) -> dict[str, Any]:
    try:
        return await push_invoice_to_xero_pipeline(
            db,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            user_id=user_id,
        )
    except XeroExportError as exc:
        if exc.blocking_errors:
            raise XeroMappingValidationError(
                XeroMappingValidationResult(
                    valid=False,
                    errors=exc.blocking_errors,
                )
            ) from exc
        raise ValueError(str(exc)) from exc


__all__ = [
    "get_invoice_xero_status",
    "push_invoice_to_xero",
    "get_export_ledger",
    "list_export_ledger",
]
