"""Vendor master CRUD — rule book detection source of truth."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_bank_reveal
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    MasterConfirmationSendResponse,
    VendorMasterCreate,
    VendorMasterResponse,
    VendorMasterUpdate,
)
from app.services.master_data.master_confirmation_service import (
    maybe_send_after_admin_change,
    send_master_confirmation,
    vendor_confirmable_patch_keys,
)
from app.services.master_data.master_data_service import (
    create_vendor_master,
    delete_vendor_master,
    list_vendor_masters,
    update_vendor_master,
)
from app.services.shared.bank_masking import apply_bank_mask_to_master, redact_bank_in_payload

router = APIRouter(prefix="/vendor-masters", tags=["vendor-masters"])


def _public_vendor(row: VendorMasterResponse, *, reveal: bool) -> VendorMasterResponse:
    return VendorMasterResponse.model_validate(
        apply_bank_mask_to_master(row.model_dump(), reveal=reveal)
    )


async def _resolve_reveal(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    reveal_bank: bool,
    scope: str,
) -> bool:
    if not reveal_bank:
        return False
    require_bank_reveal(ctx)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "bank_details_revealed",
        tenant_id=ctx.tenant_id,
        detail={"scope": scope},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return True


@router.get("", response_model=ApiEnvelope[list[VendorMasterResponse]])
async def list_vendor_master_records(
    reveal_bank: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorMasterResponse]]:
    reveal = await _resolve_reveal(db, ctx, reveal_bank=reveal_bank, scope="vendor_masters")
    rows = await list_vendor_masters(db, ctx.tenant_id)
    return ApiEnvelope(data=[_public_vendor(row, reveal=reveal) for row in rows])


@router.post("", response_model=ApiEnvelope[VendorMasterResponse], status_code=201)
async def create_vendor_master_record(
    body: VendorMasterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    actor_name, actor_email = await actor_from_context(db, ctx)
    stamped = body.model_copy(
        update={"approved_by": (actor_name or actor_email or "").strip()}
    )
    try:
        row = await create_vendor_master(db, ctx.tenant_id, stamped)
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already exists" in message.lower() else 400
        raise HTTPException(status, message) from exc
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "vendor_master_created",
        tenant_id=ctx.tenant_id,
        detail={
            "master_id": row.id,
            "name": row.name,
            "after": redact_bank_in_payload(row.model_dump(mode="json")),
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    send_result = await send_master_confirmation(
        db,
        ctx.tenant_id,
        kind="vendor",
        master_id=row.id,
    )
    if not send_result.sent and (body.contact_email or "").strip():
        await log_event(
            db,
            "vendor_master_confirmation_send_failed",
            tenant_id=ctx.tenant_id,
            detail={"master_id": row.id, "error": send_result.error},
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    rows = await list_vendor_masters(db, ctx.tenant_id)
    row = next((item for item in rows if item.id == row.id), row)
    return ApiEnvelope(data=_public_vendor(row, reveal=False))


@router.patch("/{master_id}", response_model=ApiEnvelope[VendorMasterResponse])
async def update_vendor_master_record(
    master_id: str,
    body: VendorMasterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    before_rows = await list_vendor_masters(db, ctx.tenant_id)
    before = next((row for row in before_rows if row.id == master_id), None)
    patch = body.model_dump(exclude_unset=True)
    confirmable_changed = bool(vendor_confirmable_patch_keys(patch))
    if confirmable_changed and body.status is None:
        body = body.model_copy(update={"status": "Pending registration"})
    try:
        row = await update_vendor_master(db, ctx.tenant_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "vendor_master_updated",
        tenant_id=ctx.tenant_id,
        detail={
            "master_id": master_id,
            "before": redact_bank_in_payload(before.model_dump(mode="json")) if before else None,
            "after": redact_bank_in_payload(row.model_dump(mode="json")),
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    await maybe_send_after_admin_change(
        db,
        ctx.tenant_id,
        kind="vendor",
        master_id=master_id,
        confirmable_changed=confirmable_changed,
    )
    rows = await list_vendor_masters(db, ctx.tenant_id)
    row = next((item for item in rows if item.id == master_id), row)
    return ApiEnvelope(data=_public_vendor(row, reveal=False))


@router.delete("/{master_id}", status_code=204)
async def delete_vendor_master_record(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_vendor_master(db, ctx.tenant_id, master_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{master_id}/send-confirmation", response_model=ApiEnvelope[MasterConfirmationSendResponse])
async def send_vendor_master_confirmation(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MasterConfirmationSendResponse]:
    result = await send_master_confirmation(
        db,
        ctx.tenant_id,
        kind="vendor",
        master_id=master_id,
    )
    if not result.sent:
        raise HTTPException(400, result.error or "Could not send confirmation email")
    return ApiEnvelope(
        data=MasterConfirmationSendResponse(
            sent=result.sent,
            email=result.email,
            error=result.error,
            expires_at=result.expires_at,
        )
    )
