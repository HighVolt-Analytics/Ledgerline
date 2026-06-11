"""Employee master CRUD — team expense validation source of truth."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.services.audit_service import log_event
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    EmployeeMasterCreate,
    EmployeeMasterResponse,
    EmployeeMasterUpdate,
)
from app.services.master_data_service import (
    create_employee_master,
    delete_employee_master,
    list_employee_masters,
    update_employee_master,
)

router = APIRouter(prefix="/employee-masters", tags=["employee-masters"])


@router.get("", response_model=ApiEnvelope[list[EmployeeMasterResponse]])
async def list_employee_master_records(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeMasterResponse]]:
    rows = await list_employee_masters(db, ctx.org_id)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[EmployeeMasterResponse], status_code=201)
async def create_employee_master_record(
    body: EmployeeMasterCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[EmployeeMasterResponse]:
    try:
        row = await create_employee_master(db, ctx.org_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.patch("/{master_id}", response_model=ApiEnvelope[EmployeeMasterResponse])
async def update_employee_master_record(
    master_id: str,
    body: EmployeeMasterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[EmployeeMasterResponse]:
    before_rows = await list_employee_masters(db, ctx.org_id)
    before = next((row for row in before_rows if row.id == master_id), None)
    try:
        row = await update_employee_master(db, ctx.org_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "employee_master_updated",
        org_id=ctx.org_id,
        detail={
            "master_id": master_id,
            "before": before.model_dump() if before else None,
            "after": row.model_dump(),
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=row)


@router.delete("/{master_id}", status_code=204)
async def delete_employee_master_record(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_employee_master(db, ctx.org_id, master_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
