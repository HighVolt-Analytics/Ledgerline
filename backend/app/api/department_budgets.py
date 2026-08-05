"""Department budget envelope CRUD."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.department_budget import (
    DepartmentBudgetCreate,
    DepartmentBudgetResponse,
    DepartmentBudgetUpdate,
)
from app.services.audit.audit_service import log_event
from app.services.master_data.department_budget_service import (
    create_department_budget,
    delete_department_budget,
    list_department_budgets,
    update_department_budget,
)

router = APIRouter(prefix="/department-budgets", tags=["department-budgets"])


@router.get("", response_model=ApiEnvelope[list[DepartmentBudgetResponse]])
async def list_department_budget_records(
    department: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[DepartmentBudgetResponse]]:
    rows = await list_department_budgets(db, ctx.tenant_id, department=department)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[DepartmentBudgetResponse], status_code=201)
async def create_department_budget_record(
    body: DepartmentBudgetCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[DepartmentBudgetResponse]:
    try:
        row = await create_department_budget(db, ctx.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "department_budget_created",
        tenant_id=ctx.tenant_id,
        detail={"budget": row.model_dump(mode="json")},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=row)


@router.patch("/{budget_id}", response_model=ApiEnvelope[DepartmentBudgetResponse])
async def update_department_budget_record(
    budget_id: int,
    body: DepartmentBudgetUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[DepartmentBudgetResponse]:
    try:
        row = await update_department_budget(db, ctx.tenant_id, budget_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "department_budget_updated",
        tenant_id=ctx.tenant_id,
        detail={"budget_id": budget_id, "after": row.model_dump(mode="json")},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=row)


@router.delete("/{budget_id}", status_code=204)
async def delete_department_budget_record(
    budget_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_department_budget(db, ctx.tenant_id, budget_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
