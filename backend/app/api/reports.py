"""Download generated Excel workbooks and spend analytics."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
from app.services.reports.documents_bundle_export_service import (
    build_documents_bundle_export,
)
from app.services.reports.reports_service import build_analytics, list_documents
from app.services.reports.reports_workbook_service import (
    resolve_workbook_date_filter,
    upload_workbook_blob,
    workbook_path,
)
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


@router.get("/documents-bundle/export")
async def export_documents_bundle_csv(
    date_from: Annotated[
        date | None, Query(description="Inclusive start of invoice date range")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive end of invoice date range")
    ] = None,
    format: Annotated[
        Literal["excel", "plain"],
        Query(description="Cell format: excel (HYPERLINK formulas) or plain (label | url)"),
    ] = "excel",
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download documents bundle matrix CSV for auditors."""
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
        )
    except ValueError as exc:
        raise http_bad_request(exc) from exc

    return Response(
        content=payload.csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
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
