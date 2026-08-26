"""Download generated Excel workbooks and spend analytics."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request, http_not_found
from app.schemas.common import ApiEnvelope
from app.schemas.report_catalog import (
    ReportCatalogResponse,
    ReportColumnLayoutCreate,
    ReportColumnLayoutItem,
    ReportColumnLayoutUpdate,
    ReportExportRequest,
    ReportFavouritesUpdate,
    ReportPreview,
    ReportRange,
)
from app.schemas.reports import ReportDocumentRow, ReportsAnalytics
from app.services.reports.report_catalog import (
    TE_XLSX_KIND_BY_ID,
    UnknownReportId,
    UnknownReportIds,
    catalog_items,
    get_report_or_raise,
    list_favourite_ids,
    replace_favourite_ids,
)
from app.services.reports.report_layout_service import (
    DuplicateLayoutName,
    UnknownLayoutId,
    apply_column_layout,
    create_layout,
    delete_layout,
    list_layouts,
    load_owned_layout,
    set_default_layout,
    update_layout,
)
from app.services.reports.report_export_service import export_preview
from app.services.reports.statement_builders import build_report_preview, resolve_report_window
from app.services.reports.team_expense_reports_excel import build_team_expense_excel_export
from app.schemas.reports_api import (
    DocumentsBundleExportRequest,
    ReportsAnalyticsRequest,
    ReportsDocumentsRequest,
    ReportsWorkbookRequest,
)
from app.schemas.subledger import SubledgerBalancesResponse
from app.schemas.subledger_api import SubledgerBalancesRequest
from app.schemas.department_budget import DepartmentBudgetUtilizationRow
from app.schemas.team_expense_reports import (
    EmployeeAdvanceDetailRow,
    EmployeeAdvanceSettlementRow,
    EmployeeBudgetUtilizationRow,
    EmployeeExpenseSummaryRow,
    EmployeeSpendDetailRow,
    TeamExpenseWorkspaceKpis,
)
from app.services.reports.documents_bundle_export_service import (
    build_documents_bundle_export,
)
from app.services.reports.reports_service import build_analytics, list_documents
from app.services.reports.subledger_balance_service import fetch_ap_balances, fetch_ar_balances
from app.services.reports.reports_workbook_service import (
    resolve_workbook_date_filter,
    upload_workbook_blob,
    workbook_path,
)
from app.services.master_data.department_budget_service import (
    build_department_budget_utilization_rows,
)
from app.services.reports.team_expense_reports_service import (
    build_advance_settlement_rows,
    build_budget_utilization_rows,
    build_employee_advance_detail_rows,
    build_employee_expense_summary_rows,
    build_employee_spend_detail_rows,
    build_team_expense_workspace_kpis,
)
from app.services.reports.team_expense_reports_excel import build_team_expense_excel_export
from app.services.reports.workbook_writer import write_workbook

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/catalog", response_model=ApiEnvelope[ReportCatalogResponse])
async def reports_catalog(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportCatalogResponse]:
    """Named reports plus the current user's favourite ids."""
    favourite_ids = await list_favourite_ids(db, ctx.tenant_id, ctx.user_id)
    return ApiEnvelope(
        data=ReportCatalogResponse(reports=catalog_items(), favourite_ids=favourite_ids)
    )


@router.put("/favourites", response_model=ApiEnvelope[list[str]])
async def reports_favourites_update(
    body: ReportFavouritesUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[str]]:
    """Replace the signed-in user's starred report ids."""
    if ctx.user_id is None:
        raise HTTPException(400, "Favourites require a signed-in user")
    try:
        ids = await replace_favourite_ids(
            db, ctx.tenant_id, ctx.user_id, body.report_ids
        )
    except UnknownReportIds as exc:
        raise HTTPException(422, str(exc)) from exc
    return ApiEnvelope(data=ids)


def _require_user_id(ctx: AuthContext) -> int:
    if ctx.user_id is None:
        raise HTTPException(400, "Layouts require a signed-in user")
    return ctx.user_id


@router.get(
    "/{report_id}/layouts",
    response_model=ApiEnvelope[list[ReportColumnLayoutItem]],
)
async def reports_layouts_list(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ReportColumnLayoutItem]]:
    user_id = _require_user_id(ctx)
    try:
        rows = await list_layouts(db, ctx.tenant_id, user_id, report_id)
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=rows)


@router.post(
    "/{report_id}/layouts",
    response_model=ApiEnvelope[ReportColumnLayoutItem],
)
async def reports_layouts_create(
    report_id: str,
    body: ReportColumnLayoutCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportColumnLayoutItem]:
    user_id = _require_user_id(ctx)
    try:
        row = await create_layout(
            db,
            ctx.tenant_id,
            user_id,
            report_id,
            name=body.name,
            column_config=body.column_config,
            is_default=body.is_default,
        )
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except DuplicateLayoutName as exc:
        raise HTTPException(422, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.patch(
    "/{report_id}/layouts/{layout_id}",
    response_model=ApiEnvelope[ReportColumnLayoutItem],
)
async def reports_layouts_update(
    report_id: str,
    layout_id: int,
    body: ReportColumnLayoutUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportColumnLayoutItem]:
    user_id = _require_user_id(ctx)
    try:
        row = await update_layout(
            db,
            ctx.tenant_id,
            user_id,
            report_id,
            layout_id,
            name=body.name,
            column_config=body.column_config,
        )
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except UnknownLayoutId as exc:
        raise http_not_found(exc) from exc
    except DuplicateLayoutName as exc:
        raise HTTPException(422, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.post(
    "/{report_id}/layouts/{layout_id}/default",
    response_model=ApiEnvelope[ReportColumnLayoutItem],
)
async def reports_layouts_set_default(
    report_id: str,
    layout_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportColumnLayoutItem]:
    user_id = _require_user_id(ctx)
    try:
        row = await set_default_layout(
            db, ctx.tenant_id, user_id, report_id, layout_id
        )
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except UnknownLayoutId as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=row)


@router.delete("/{report_id}/layouts/{layout_id}", response_model=ApiEnvelope[None])
async def reports_layouts_delete(
    report_id: str,
    layout_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[None]:
    user_id = _require_user_id(ctx)
    try:
        await delete_layout(db, ctx.tenant_id, user_id, report_id, layout_id)
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except UnknownLayoutId as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=None)


def _preview_query(
    range_key: ReportRange,
    compare: bool,
    date_from: date | None,
    date_to: date | None,
) -> dict:
    return {
        "range_key": range_key,
        "compare": compare,
        "date_from": date_from,
        "date_to": date_to,
    }


@router.get("/{report_id}/preview", response_model=ApiEnvelope[ReportPreview])
async def reports_preview(
    report_id: str,
    range: Annotated[ReportRange, Query()] = "month",
    compare: bool = False,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportPreview]:
    """Live report rows for the selected range (no hardcoded sample data)."""
    try:
        preview = await build_report_preview(
            db,
            ctx.tenant_id,
            report_id,
            **_preview_query(range, compare, date_from, date_to),
        )
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=preview)


@router.post("/{report_id}/export")
async def reports_export(
    report_id: str,
    body: ReportExportRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download the selected report as PDF or Excel for the chosen range."""
    try:
        if body.format == "xlsx" and report_id in TE_XLSX_KIND_BY_ID and body.layout_id is None:
            get_report_or_raise(report_id)
            start, end = await resolve_report_window(
                db,
                ctx.tenant_id,
                body.range,
                body.date_from,
                body.date_to,
            )
            te = await build_team_expense_excel_export(
                db,
                ctx.tenant_id,
                report=TE_XLSX_KIND_BY_ID[report_id],
                tenant_slug=ctx.tenant_slug or "tenant",
                date_from=start,
                date_to=end,
                as_of=body.range != "custom",
            )
            return Response(
                content=te.xlsx_bytes,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": f'attachment; filename="{te.filename}"',
                    "X-Data-Rows": str(te.data_rows),
                    "X-Page-Count": "1",
                },
            )
        preview = await build_report_preview(
            db,
            ctx.tenant_id,
            report_id,
            range_key=body.range,
            compare=body.compare,
            date_from=body.date_from,
            date_to=body.date_to,
        )
        if body.layout_id is not None:
            if ctx.user_id is None:
                raise HTTPException(400, "Layouts require a signed-in user")
            layout = await load_owned_layout(
                db,
                ctx.tenant_id,
                ctx.user_id,
                report_id,
                body.layout_id,
            )
            preview = apply_column_layout(preview, layout.column_config.columns)
        payload = export_preview(preview, body.format)
    except UnknownReportId as exc:
        raise http_not_found(exc) from exc
    except UnknownLayoutId as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return Response(
        content=payload.body,
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "X-Data-Rows": str(payload.data_rows),
            "X-Page-Count": str(payload.page_count),
        },
    )


@router.get("/analytics", response_model=ApiEnvelope[ReportsAnalytics])
async def reports_analytics(
    month: Annotated[
        str | None,
        Query(
            description="Period as YYYY-MM (defaults to current month)",
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        ),
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportsAnalytics]:
    """Spend analytics, GL distribution, and vendor summary for the Reports page."""
    params = ReportsAnalyticsRequest(month=month)
    return ApiEnvelope(
        data=await build_analytics(db, tenant_id=ctx.tenant_id, month=params.month)
    )


@router.get("/documents", response_model=ApiEnvelope[list[ReportDocumentRow]])
async def reports_documents(
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ReportDocumentRow]]:
    """Processed invoice rows for CSV export."""
    params = ReportsDocumentsRequest(date_from=date_from, date_to=date_to)
    try:
        rows = await list_documents(
            db,
            tenant_id=ctx.tenant_id,
            date_from=params.date_from,
            date_to=params.date_to,
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=rows)


@router.get("/subledger/ap-balances", response_model=ApiEnvelope[SubledgerBalancesResponse])
async def reports_ap_balances(
    as_of: Annotated[
        date | None, Query(description="Balances as of this date (inclusive)")
    ] = None,
    include_unregistered: Annotated[
        bool, Query(description="Include vendors not in the registry")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SubledgerBalancesResponse]:
    """Accounts payable balances grouped by vendor registry."""
    params = SubledgerBalancesRequest(
        as_of=as_of,
        include_unregistered=include_unregistered,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(
        data=await fetch_ap_balances(
            db,
            ctx.tenant_id,
            as_of=params.as_of,
            include_unregistered=params.include_unregistered,
            limit=params.limit,
            offset=params.offset,
        )
    )


@router.get("/subledger/ar-balances", response_model=ApiEnvelope[SubledgerBalancesResponse])
async def reports_ar_balances(
    as_of: Annotated[
        date | None, Query(description="Balances as of this date (inclusive)")
    ] = None,
    include_unregistered: Annotated[
        bool, Query(description="Include customers not in the registry")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SubledgerBalancesResponse]:
    """Accounts receivable balances grouped by customer registry."""
    params = SubledgerBalancesRequest(
        as_of=as_of,
        include_unregistered=include_unregistered,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(
        data=await fetch_ar_balances(
            db,
            ctx.tenant_id,
            as_of=params.as_of,
            include_unregistered=params.include_unregistered,
            limit=params.limit,
            offset=params.offset,
        )
    )


@router.get(
    "/team-expenses/advance-settlement",
    response_model=ApiEnvelope[list[EmployeeAdvanceSettlementRow]],
)
async def reports_team_expense_advance_settlement(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeAdvanceSettlementRow]]:
    """Employee Staff Advance float: took, used, outstanding, available."""
    rows = await build_advance_settlement_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get(
    "/team-expenses/budget-utilization",
    response_model=ApiEnvelope[list[EmployeeBudgetUtilizationRow]],
)
@router.get(
    "/team-expenses/spending-limit-utilization",
    response_model=ApiEnvelope[list[EmployeeBudgetUtilizationRow]],
    include_in_schema=False,
)
async def reports_team_expense_budget_utilization(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeBudgetUtilizationRow]]:
    """Employee spending limits vs MTD/QTD/YTD claim spend (computed from invoices)."""
    rows = await build_budget_utilization_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get(
    "/team-expenses/department-budget-utilization",
    response_model=ApiEnvelope[list[DepartmentBudgetUtilizationRow]],
)
async def reports_team_expense_department_budget_utilization(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[DepartmentBudgetUtilizationRow]]:
    """GL account budgets vs claim spend for the current period (soft/hard enforcement)."""
    rows = await build_department_budget_utilization_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get(
    "/team-expenses/workspace-kpis",
    response_model=ApiEnvelope[TeamExpenseWorkspaceKpis],
)
async def reports_team_expense_workspace_kpis(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[TeamExpenseWorkspaceKpis]:
    """Open / pending / posted-this-month KPIs for the Team Expenses page."""
    return ApiEnvelope(data=await build_team_expense_workspace_kpis(db, ctx.tenant_id))


@router.get(
    "/expenses/workspace-kpis",
    response_model=ApiEnvelope[TeamExpenseWorkspaceKpis],
)
async def reports_expenses_workspace_kpis(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[TeamExpenseWorkspaceKpis]:
    """Open / pending / posted-this-month KPIs for Expenses Management."""
    from app.services.invoice.invoice_evaluation_service import ROUTE_EXPENSES

    return ApiEnvelope(
        data=await build_team_expense_workspace_kpis(
            db,
            ctx.tenant_id,
            route_target=ROUTE_EXPENSES,
            include_kinds=False,
        )
    )


@router.get(
    "/team-expenses/expense-summary",
    response_model=ApiEnvelope[list[EmployeeExpenseSummaryRow]],
)
async def reports_team_expense_expense_summary(
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeExpenseSummaryRow]]:
    """Team expense documents with employee, line item, ledger, and status."""
    params = ReportsDocumentsRequest(date_from=date_from, date_to=date_to)
    try:
        rows = await build_employee_expense_summary_rows(
            db,
            ctx.tenant_id,
            date_from=params.date_from,
            date_to=params.date_to,
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=rows)


@router.get(
    "/team-expenses/employee-spend-detail",
    response_model=ApiEnvelope[list[EmployeeSpendDetailRow]],
)
async def reports_team_expense_employee_spend_detail(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeSpendDetailRow]]:
    """Employee × Sub-GL YTD spend vs Sub-GL budget (employee-wise budget utilization)."""
    rows = await build_employee_spend_detail_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get(
    "/team-expenses/employee-advance-detail",
    response_model=ApiEnvelope[list[EmployeeAdvanceDetailRow]],
)
async def reports_team_expense_employee_advance_detail(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[EmployeeAdvanceDetailRow]]:
    """Staff Advance movement ledger: one row per Took (advance) and Used (claim netting)."""
    rows = await build_employee_advance_detail_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get("/team-expenses/{report}/export")
async def export_team_expense_report(
    report: Annotated[
        Literal[
            "budget-utilization",
            "spending-limit-utilization",
            "department-budget-utilization",
            "expense-summary",
            "employee-spend-detail",
            "employee-advance-detail",
        ],
        Path(description="Which team expense finance workbook to build"),
    ],
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download a styled Excel workbook for Team Expense finance reporting."""
    try:
        payload = await build_team_expense_excel_export(
            db,
            ctx.tenant_id,
            report=report,
            tenant_slug=ctx.tenant_slug or "tenant",
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc

    return Response(
        content=payload.xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "X-Data-Rows": str(payload.data_rows),
        },
    )


@router.get("/documents-bundle/export")
async def export_documents_bundle(
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    format: Annotated[
        Literal["excel", "plain"],
        Query(
            description="Link cells: excel (clickable hyperlinks) or plain (label | url text)"
        ),
    ] = "excel",
    tz: Annotated[
        str | None,
        Query(
            description="IANA timezone for Timestamp column (browser local); DB stays UTC"
        ),
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download documents bundle matrix as a styled Excel workbook for auditors."""
    params = DocumentsBundleExportRequest(
        date_from=date_from,
        date_to=date_to,
        format=format,
    )
    try:
        payload = await build_documents_bundle_export(
            db,
            tenant_id=ctx.tenant_id,
            date_from=params.date_from,
            date_to=params.date_to,
            cell_format=params.format,
            display_timezone=tz,
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc

    return Response(
        content=payload.xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "X-Data-Rows": str(payload.data_rows),
        },
    )


@router.post("/generate", response_model=ApiEnvelope[dict[str, str]])
async def generate_report(
    background_tasks: BackgroundTasks,
    workbook_date: Annotated[
        date | None,
        Query(description="Legacy: single invoice date (same as date_from=date_to)"),
    ] = None,
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, str]]:
    """Build or refresh the output workbook from current database state."""
    params = ReportsWorkbookRequest(
        workbook_date=workbook_date,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        d_from, d_to = resolve_workbook_date_filter(
            params.workbook_date, params.date_from, params.date_to
        )
        path = await write_workbook(
            db,
            ctx.tenant_id,
            date_from=d_from,
            date_to=d_to,
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    background_tasks.add_task(upload_workbook_blob, ctx.tenant_id, path)
    return ApiEnvelope(data={"path": str(path), "filename": path.name})


@router.get("/download")
async def download_report(
    workbook_date: Annotated[
        date | None,
        Query(description="Legacy: single invoice date (same as date_from=date_to)"),
    ] = None,
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    ctx: AuthContext = Depends(get_auth_context),
) -> FileResponse:
    """Download the generated workbook file."""
    params = ReportsWorkbookRequest(
        workbook_date=workbook_date,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        d_from, d_to = resolve_workbook_date_filter(
            params.workbook_date, params.date_from, params.date_to
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    path = workbook_path(
        ctx.tenant_id,
        ctx.tenant_slug,
        date_from=d_from,
        date_to=d_to,
    )

    if not path.is_file():
        raise HTTPException(
            404,
            "Workbook not found. Run POST /api/reports/generate first.",
        )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )
