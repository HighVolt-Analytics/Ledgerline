"""Download generated Excel workbooks and spend analytics."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request
from app.schemas.common import ApiEnvelope
from app.schemas.reports import ReportDocumentRow, ReportsAnalytics
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
    EmployeeAdvanceSettlementRow,
    EmployeeBudgetUtilizationRow,
    EmployeeExpenseSummaryRow,
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
    build_employee_expense_summary_rows,
)
from app.services.reports.team_expense_reports_excel import build_team_expense_excel_export
from app.services.reports.workbook_writer import write_workbook

router = APIRouter(prefix="/reports", tags=["reports"])


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
    """Employee advance ledger, pending against-advance, and available float."""
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
    """Department budget envelopes vs consumed Team Expense spend for the current period."""
    rows = await build_department_budget_utilization_rows(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


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


@router.get("/team-expenses/{report}/export")
async def export_team_expense_report(
    report: Annotated[
        Literal[
            "advance-settlement",
            "budget-utilization",
            "spending-limit-utilization",
            "department-budget-utilization",
            "expense-summary",
        ],
        Path(description="Which team expense report workbook to build"),
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
    """Download a styled Excel workbook for one Team Expense report."""
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
