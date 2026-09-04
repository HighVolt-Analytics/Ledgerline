"""Xero accounting export pipeline APIs (export, refresh, contacts)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_db, require_admin
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.common import ApiEnvelope
from app.services.audit.audit_service import log_event
from app.services.integration.accounting_integration_service import require_xero_ready
from app.integrations.xero.client import XeroApiError
from app.integrations.xero.contacts import (
    create_xero_supplier_contact,
    resolve_supplier_contact,
    save_supplier_contact_mapping,
)
from app.integrations.xero.export import (
    XeroExportError,
    export_supplier_invoice_to_xero,
    get_export_ledger,
    ledger_to_dict,
    list_export_ledger,
    refresh_export_from_xero,
    retry_attachment,
    validate_invoice_for_xero_export,
)
from app.integrations.xero.reconcile import (
    run_export_reconciliation,
)

router = APIRouter(prefix="/integrations/xero", tags=["xero-export-pipeline"])


class ContactResolveBody(BaseModel):
    supplier_key: str
    legal_name: str
    tax_id: str | None = None
    email: str | None = None
    existing_contact_id: str | None = None
    save_mapping: bool = True


class ContactCreateBody(BaseModel):
    legal_name: str
    supplier_key: str | None = None
    tax_id: str | None = None
    email: str | None = None


def _http_export_error(exc: XeroExportError) -> HTTPException:
    status = 400
    if exc.code in {"not_found", "invoice_not_found"}:
        status = 404
    if exc.code in {"in_flight"}:
        status = 409
    return HTTPException(
        status,
        detail={
            "message": str(exc),
            "code": exc.code,
            "bucket": exc.bucket,
            "blocking_errors": exc.blocking_errors,
            "evidence": ledger_to_dict(exc.ledger) if exc.ledger else None,
        },
    )


@router.post("/contacts/resolve")
async def contacts_resolve(
    body: ContactResolveBody,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    _, xero_tenant_id = await require_xero_ready(db, ctx.tenant_id)
    match = await resolve_supplier_contact(
        db,
        tenant_id=ctx.tenant_id,
        xero_tenant_id=xero_tenant_id,
        supplier_key=body.supplier_key,
        legal_name=body.legal_name,
        tax_id=body.tax_id,
        email=body.email,
        existing_contact_id=body.existing_contact_id,
    )
    if body.save_mapping and match.contact_id and match.outcome in {"matched", "mapped"}:
        await save_supplier_contact_mapping(
            db,
            tenant_id=ctx.tenant_id,
            supplier_key=body.supplier_key,
            legal_name=body.legal_name,
            contact_id=match.contact_id,
            user_id=ctx.user_id,
            xero_tenant_id=xero_tenant_id,
        )
        await log_event(
            db,
            "xero_contact_matched",
            tenant_id=ctx.tenant_id,
            detail={
                "supplier_key": body.supplier_key,
                "contact_id": match.contact_id,
                "reason": match.reason,
            },
        )
        await db.commit()
    return ApiEnvelope(
        data={
            "outcome": match.outcome,
            "contact_id": match.contact_id,
            "reason": match.reason,
            "candidates": match.candidates,
        }
    )


@router.post("/contacts/create")
async def contacts_create(
    body: ContactCreateBody,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    legal_name = body.legal_name.strip()
    if not legal_name:
        raise HTTPException(400, detail={"message": "Contact name is required", "code": "name_required"})
    supplier_key = (body.supplier_key or legal_name).strip()
    try:
        result = await create_xero_supplier_contact(
            db,
            tenant_id=ctx.tenant_id,
            supplier_key=supplier_key,
            legal_name=legal_name,
            tax_id=body.tax_id,
            email=body.email,
            user_id=ctx.user_id,
        )
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(400, detail={"message": code, "code": code}) from exc
    except XeroApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await log_event(
        db,
        "xero_contact_created",
        tenant_id=ctx.tenant_id,
        detail=result,
    )
    await db.commit()
    return ApiEnvelope(data=result)


@router.post("/invoices/{invoice_id}/validate")
async def invoices_validate(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    data = await validate_invoice_for_xero_export(
        db, tenant_id=ctx.tenant_id, invoice_id=invoice_id
    )
    await log_event(
        db,
        "xero_export_validated",
        tenant_id=ctx.tenant_id,
        detail={"invoice_id": invoice_id, "valid": data["valid"]},
    )
    await db.commit()
    return ApiEnvelope(data=data)


@router.post("/invoices/{invoice_id}/export")
async def invoices_export(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "xero_export_started",
        tenant_id=ctx.tenant_id,
        detail={"invoice_id": invoice_id},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    try:
        result = await export_supplier_invoice_to_xero(
            db,
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            user_id=ctx.user_id,
        )
    except XeroExportError as exc:
        await log_event(
            db,
            "xero_export_failed",
            tenant_id=ctx.tenant_id,
            detail={
                "invoice_id": invoice_id,
                "code": exc.code,
                "bucket": exc.bucket,
                "blocking_errors": exc.blocking_errors,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )
        await db.commit()
        raise _http_export_error(exc) from exc
    evidence = result.get("evidence") or {}
    await log_event(
        db,
        "xero_export_succeeded",
        tenant_id=ctx.tenant_id,
        detail={
            "invoice_id": invoice_id,
            "sync_id": evidence.get("sync_id"),
            "external_id": evidence.get("external_id"),
            "attachment_status": evidence.get("attachment_status"),
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    await db.commit()
    return ApiEnvelope(data=result)


@router.get("/exports")
async def exports_list(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    data = await list_export_ledger(
        db,
        tenant_id=ctx.tenant_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return ApiEnvelope(data=data)


@router.get("/exports/{sync_id}")
async def exports_get(
    sync_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    row = await get_export_ledger(db, tenant_id=ctx.tenant_id, sync_id=sync_id)
    if row is None:
        raise HTTPException(404, "Export not found")
    return ApiEnvelope(data=ledger_to_dict(row))


@router.post("/exports/{sync_id}/refresh")
async def exports_refresh(
    sync_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        result = await refresh_export_from_xero(
            db, tenant_id=ctx.tenant_id, sync_id=sync_id
        )
    except XeroExportError as exc:
        raise _http_export_error(exc) from exc
    await log_event(
        db,
        "xero_export_refreshed",
        tenant_id=ctx.tenant_id,
        detail={"sync_id": sync_id, "flags": result.get("divergence_flags")},
    )
    await db.commit()
    return ApiEnvelope(data=result)


@router.post("/exports/{sync_id}/retry-attachment")
async def exports_retry_attachment(
    sync_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        result = await retry_attachment(db, tenant_id=ctx.tenant_id, sync_id=sync_id)
    except XeroExportError as exc:
        raise _http_export_error(exc) from exc
    await log_event(
        db,
        "xero_attachment_retry",
        tenant_id=ctx.tenant_id,
        detail={
            "sync_id": sync_id,
            "attachment_status": (result.get("evidence") or {}).get("attachment_status"),
        },
    )
    await db.commit()
    return ApiEnvelope(data=result)


@router.get("/export-queue")
async def export_queue(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    """Eligible processed supplier invoices with validation status."""
    invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == ctx.tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
            )
            .order_by(Invoice.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    items: list[dict[str, Any]] = []
    for inv in invoices:
        if (inv.route_target or "").strip() == "sales":
            continue
        validation = await validate_invoice_for_xero_export(
            db, tenant_id=ctx.tenant_id, invoice_id=inv.id
        )
        items.append(
            {
                "invoice_id": inv.id,
                "invoice_no": inv.invoice_no,
                "vendor": inv.vendor,
                "total": float(inv.total) if inv.total is not None else None,
                "currency": inv.currency,
                "valid": validation["valid"],
                "blocking_errors": validation["blocking_errors"],
            }
        )
    return ApiEnvelope(data={"items": items})


@router.post("/reconciliation/run")
async def reconciliation_run(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    result = await run_export_reconciliation(
        db, tenant_id=ctx.tenant_id, initiated_by=ctx.user_id
    )
    await log_event(
        db,
        "xero_reconciliation_run",
        tenant_id=ctx.tenant_id,
        detail={
            "checked": result.get("checked"),
            "divergences": len(result.get("divergences") or []),
        },
    )
    await db.commit()
    return ApiEnvelope(data=result)
