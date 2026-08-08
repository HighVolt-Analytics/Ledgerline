"""Department budget envelope CRUD."""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.department_budget import (
    DepartmentBudgetCreate,
    DepartmentBudgetImportResultResponse,
    DepartmentBudgetImportRowErrorResponse,
    DepartmentBudgetImportRowPreviewResponse,
    DepartmentBudgetResponse,
    DepartmentBudgetUpdate,
    ParentGlBudgetTreeUpsert,
    PeriodKind,
)
from app.services.audit.audit_service import log_event
from app.services.master_data.department_budget_import_service import (
    build_budget_import_template,
    import_department_budgets,
    parse_budget_import_file,
)
from app.services.master_data.department_budget_service import (
    create_department_budget,
    delete_department_budget,
    delete_parent_gl_budget_tree,
    list_department_budgets,
    update_department_budget,
    upsert_parent_gl_budget_tree,
)

router = APIRouter(prefix="/department-budgets", tags=["department-budgets"])

PeriodKindQuery = Literal["monthly", "quarterly", "annual"]


def _import_result_response(result) -> DepartmentBudgetImportResultResponse:
    return DepartmentBudgetImportResultResponse(
        dry_run=result.dry_run,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=[
            DepartmentBudgetImportRowErrorResponse(
                row_number=row.row_number,
                parent_gl=row.parent_gl,
                message=row.message,
            )
            for row in result.errors
        ],
        previews=[
            DepartmentBudgetImportRowPreviewResponse(
                row_number=row.row_number,
                parent_gl=row.parent_gl,
                period_kind=row.period_kind,
                period_key=row.period_key,
                action=row.action,
                detail=row.detail,
            )
            for row in result.previews
        ],
    )


@router.get("", response_model=ApiEnvelope[list[DepartmentBudgetResponse]])
async def list_department_budget_records(
    department: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[DepartmentBudgetResponse]]:
    rows = await list_department_budgets(db, ctx.tenant_id, department=department)
    return ApiEnvelope(data=rows)


@router.get("/import/template")
async def download_department_budget_import_template(
    period_kind: PeriodKindQuery = Query("monthly"),
    period_key: str | None = Query(None),
    prefill_coa: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> Response:
    """Download an Excel template prefilled with Expense COA parent + Sub-GL rows."""
    try:
        content = await build_budget_import_template(
            db,
            ctx.tenant_id,
            period_kind=period_kind,  # type: ignore[arg-type]
            period_key=period_key,
            prefill_coa=prefill_coa,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    kind: PeriodKind = period_kind  # type: ignore[assignment]
    filename = f"gl-budget-{kind}-template.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ApiEnvelope[DepartmentBudgetImportResultResponse])
async def import_department_budget_file(
    request: Request,
    dry_run: bool = Query(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[DepartmentBudgetImportResultResponse]:
    """Preview or apply bulk Parent GL + Sub-GL budget upserts from CSV/XLSX."""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    try:
        rows = parse_budget_import_file(raw, file.filename or "import.xlsx")
        result = await import_department_budgets(
            db,
            ctx.tenant_id,
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
            "department_budget_import_completed",
            tenant_id=ctx.tenant_id,
            detail={
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


@router.put("/tree", response_model=ApiEnvelope[list[DepartmentBudgetResponse]])
async def upsert_parent_gl_budget_tree_record(
    body: ParentGlBudgetTreeUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[list[DepartmentBudgetResponse]]:
    """Save parent GL budget and all Sub-GL slices (sum must equal parent)."""
    try:
        rows = await upsert_parent_gl_budget_tree(db, ctx.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "department_budget_tree_upserted",
        tenant_id=ctx.tenant_id,
        detail={
            "parent_gl": body.parent_gl,
            "period_kind": body.period_kind,
            "period_key": body.period_key,
            "allocated": str(body.allocated),
            "sub_count": len(body.sub_allocations),
            "rows": [row.model_dump(mode="json") for row in rows],
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=rows)


@router.delete("/tree", status_code=204)
async def delete_parent_gl_budget_tree_record(
    parent_gl: str = Query(...),
    period_kind: str = Query(...),
    period_key: str = Query(...),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_parent_gl_budget_tree(
            db,
            ctx.tenant_id,
            parent_gl=parent_gl,
            period_kind=period_kind,
            period_key=period_key,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
