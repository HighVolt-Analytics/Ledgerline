"""Customer master CRUD API."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.customer import CustomerMasterCreate, CustomerMasterResponse, CustomerMasterUpdate
from app.services.audit.audit_service import log_event
from app.services.master_data.customer_master_service import (
    create_customer_master,
    delete_customer_master,
    list_customer_masters,
    update_customer_master,
)

router = APIRouter(prefix="/customer-masters", tags=["customer-masters"])


@router.get("", response_model=ApiEnvelope[list[CustomerMasterResponse]])
async def list_customer_master_records(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[CustomerMasterResponse]]:
    rows = await list_customer_masters(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[CustomerMasterResponse], status_code=201)
async def create_customer_master_record(
    body: CustomerMasterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[CustomerMasterResponse]:
    try:
        row = await create_customer_master(db, ctx.tenant_id, body)
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already exists" in message.lower() else 400
        raise HTTPException(status, message) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "customer_master_created",
        tenant_id=ctx.tenant_id,
        detail={"master_id": row.id, "name": row.name, "after": row.model_dump()},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=row)


@router.patch("/{master_id}", response_model=ApiEnvelope[CustomerMasterResponse])
async def update_customer_master_record(
    master_id: str,
    body: CustomerMasterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[CustomerMasterResponse]:
    before_rows = await list_customer_masters(db, ctx.tenant_id)
    before = next((row for row in before_rows if row.id == master_id), None)
    try:
        row = await update_customer_master(db, ctx.tenant_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "customer_master_updated",
        tenant_id=ctx.tenant_id,
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
async def delete_customer_master_record(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_customer_master(db, ctx.tenant_id, master_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
