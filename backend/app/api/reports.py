"""Download generated Excel workbooks and spend analytics."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request
from app.schemas.common import ApiEnvelope
from app.schemas.reports import ReportDocumentRow, ReportsAnalytics
from app.schemas.reports_api import (
    ReportsAnalyticsRequest,
    ReportsDocumentsRequest,
    ReportsWorkbookRequest,
)
from app.services.reports_service import build_analytics, list_documents
from app.services.reports_workbook_service import (
    resolve_workbook_date_filter,
    upload_workbook_blob,
    workbook_path,
)
from app.services.workbook_writer import write_workbook

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/analytics", response_model=ApiEnvelope[ReportsAnalytics])
async def reports_analytics(
    params: Annotated[ReportsAnalyticsRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportsAnalytics]:
    """Spend analytics, GL distribution, and vendor summary for the Reports page."""
    return ApiEnvelope(
        data=await build_analytics(db, tenant_id=ctx.tenant_id, month=params.month)
    )


@router.get("/documents", response_model=ApiEnvelope[list[ReportDocumentRow]])
async def reports_documents(
    params: Annotated[ReportsDocumentsRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ReportDocumentRow]]:
    """Processed invoice rows for CSV export."""
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


@router.post("/generate", response_model=ApiEnvelope[dict[str, str]])
async def generate_report(
    background_tasks: BackgroundTasks,
    params: Annotated[ReportsWorkbookRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, str]]:
    """Build or refresh the output workbook from current database state."""
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
    params: Annotated[ReportsWorkbookRequest, Query()],
    ctx: AuthContext = Depends(get_auth_context),
) -> FileResponse:
    """Download the generated workbook file."""
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
