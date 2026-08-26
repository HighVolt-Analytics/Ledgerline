"""Employee master CRUD — team expense validation source of truth."""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_bank_reveal
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    EmployeeImportResultResponse,
    EmployeeImportRowErrorResponse,
    EmployeeImportRowPreviewResponse,
    EmployeeMasterCreate,
    EmployeeMasterResponse,
    EmployeeMasterUpdate,
    MasterConfirmationSendResponse,
)
from app.services.master_data.master_confirmation_service import (
    employee_confirmable_patch_keys,
    maybe_send_after_admin_change,
    send_master_confirmation,
)
from app.services.master_data.employee_import_service import (
    build_import_template,
    import_employee_masters,
    parse_employee_import_file,
)
from app.services.master_data.master_data_service import (
    create_employee_master,
    delete_employee_master,
    list_employee_masters,
    update_employee_master,
)
from app.services.shared.bank_masking import apply_bank_mask_to_master, redact_bank_in_payload

router = APIRouter(prefix="/employee-masters", tags=["employee-masters"])

EmployeeImportMode = Literal["register", "payment"]


def _public_employee(row: EmployeeMasterResponse, *, reveal: bool) -> EmployeeMasterResponse:
    return EmployeeMasterResponse.model_validate(
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


def _import_result_response(result) -> EmployeeImportResultResponse:
    return EmployeeImportResultResponse(
        mode=result.mode,
        dry_run=result.dry_run,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=[
            EmployeeImportRowErrorResponse(
                row_number=row.row_number,
                email=row.email,
                message=row.message,
            )
            for row in result.errors
        ],
        previews=[
            EmployeeImportRowPreviewResponse(
                row_number=row.row_number,
                email=row.email,
                name=row.name,
                action=row.action,
                detail=row.detail,
            )
            for row in result.previews
        ],
    )


@router.get("/import/templates/{mode}")
async def download_employee_import_template(
    mode: EmployeeImportMode,
    ctx: AuthContext = Depends(require_admin),
) -> Response:
    content = build_import_template(mode)
    filename = f"employee-{mode}-template.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ApiEnvelope[EmployeeImportResultResponse])
async def import_employee_master_file(
    request: Request,
    mode: EmployeeImportMode = Query(...),
    dry_run: bool = Query(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[EmployeeImportResultResponse]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    try:
        rows = parse_employee_import_file(raw, file.filename or "import.xlsx")
        result = await import_employee_masters(
            db,
            ctx.tenant_id,
            mode=mode,
            rows=rows,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not dry_run and (result.created or result.updated):
        actor_name, actor_email = await actor_from_context(db, ctx)
        client_ip = request.client.host if request.client else None
        await log_event(
            db,
            "employee_import_completed",
            tenant_id=ctx.tenant_id,
            detail={
                "mode": mode,
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
                "error_count": len(result.errors),
                "filename": file.filename,
            },
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )

    return ApiEnvelope(data=_import_result_response(result))


@router.get("", response_model=ApiEnvelope[list[EmployeeMasterResponse]])
async def list_employee_master_records(
    reveal_bank: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeMasterResponse]]:
    reveal = await _resolve_reveal(db, ctx, reveal_bank=reveal_bank, scope="employee_masters")
    rows = await list_employee_masters(db, ctx.tenant_id)
    return ApiEnvelope(data=[_public_employee(row, reveal=reveal) for row in rows])


@router.post("", response_model=ApiEnvelope[EmployeeMasterResponse], status_code=201)
async def create_employee_master_record(
    body: EmployeeMasterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[EmployeeMasterResponse]:
    try:
        row = await create_employee_master(db, ctx.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    send_result = await send_master_confirmation(
        db,
        ctx.tenant_id,
        kind="employee",
        master_id=row.id,
    )
    if not send_result.sent and (body.email or "").strip():
        actor_name, actor_email = await actor_from_context(db, ctx)
        client_ip = request.client.host if request.client else None
        await log_event(
            db,
            "employee_master_confirmation_send_failed",
            tenant_id=ctx.tenant_id,
            detail={"master_id": row.id, "error": send_result.error},
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    rows = await list_employee_masters(db, ctx.tenant_id)
    row = next((item for item in rows if item.id == row.id), row)
    return ApiEnvelope(data=_public_employee(row, reveal=False))


@router.patch("/{master_id}", response_model=ApiEnvelope[EmployeeMasterResponse])
async def update_employee_master_record(
    master_id: str,
    body: EmployeeMasterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[EmployeeMasterResponse]:
    before_rows = await list_employee_masters(db, ctx.tenant_id)
    before = next((row for row in before_rows if row.id == master_id), None)
    patch = body.model_dump(exclude_unset=True)
    confirmable_changed = bool(employee_confirmable_patch_keys(patch))
    if confirmable_changed and body.status is None:
        body = body.model_copy(update={"status": "Pending verification"})
    try:
        row = await update_employee_master(db, ctx.tenant_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        detail = exc.errors()[0].get("msg") if exc.errors() else "Invalid employee or chart of accounts"
        raise HTTPException(400, str(detail)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "employee_master_updated",
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
        kind="employee",
        master_id=master_id,
        confirmable_changed=confirmable_changed,
    )
    rows = await list_employee_masters(db, ctx.tenant_id)
    row = next((item for item in rows if item.id == master_id), row)
    return ApiEnvelope(data=_public_employee(row, reveal=False))


@router.delete("/{master_id}", status_code=204)
async def delete_employee_master_record(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_employee_master(db, ctx.tenant_id, master_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{master_id}/send-confirmation", response_model=ApiEnvelope[MasterConfirmationSendResponse])
async def send_employee_master_confirmation(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MasterConfirmationSendResponse]:
    result = await send_master_confirmation(
        db,
        ctx.tenant_id,
        kind="employee",
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
