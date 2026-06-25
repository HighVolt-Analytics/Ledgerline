"""Download generated Excel workbooks and spend analytics."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.schemas.reports import ReportDocumentRow, ReportsAnalytics
from app.services import blob_storage
from app.services.reports_service import build_analytics, list_documents
from app.services.tenant_storage_paths import tenant_blob_name, tenant_local_dir
from app.services.workbook_writer import workbook_filename, write_workbook
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _reports_dir(tenant_id) -> Path:
    return tenant_local_dir(tenant_id, "reports")


def _resolve_date_filter(
    workbook_date: date | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date | None, date | None]:
    """Merge legacy single-day param with inclusive range."""
    if workbook_date is not None:
        if date_from is None and date_to is None:
            return workbook_date, workbook_date
        date_from = date_from or workbook_date
        date_to = date_to or workbook_date
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(400, "date_from must be on or before date_to")
    return date_from, date_to


def _upload_workbook_blob(tenant_id, path: Path) -> None:
    """Upload workbook to blob storage without blocking the HTTP response."""
    if not blob_storage.is_blob_enabled():
        return
    try:
        blob_name = tenant_blob_name(tenant_id, f"reports/{path.name}")
        blob_storage.upload_bytes(blob_name, path.read_bytes())
        logger.info("workbook_uploaded_blob", blob_name=blob_name)
    except Exception as exc:
        logger.warning("workbook_blob_upload_failed", path=str(path), error=str(exc))


@router.get("/analytics", response_model=ApiEnvelope[ReportsAnalytics])
async def reports_analytics(
    month: str | None = Query(
        None,
        description="Period as YYYY-MM (defaults to current month)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReportsAnalytics]:
    """Spend analytics, GL distribution, and vendor summary for the Reports page."""
    return ApiEnvelope(
        data=await build_analytics(db, tenant_id=ctx.tenant_id, month=month)
    )


@router.get("/documents", response_model=ApiEnvelope[list[ReportDocumentRow]])
async def reports_documents(
    date_from: date | None = Query(None, description="Inclusive start of invoice date range"),
    date_to: date | None = Query(None, description="Inclusive end of invoice date range"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ReportDocumentRow]]:
    """Processed invoice rows for CSV export."""
    try:
        rows = await list_documents(
            db,
            tenant_id=ctx.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=rows)


@router.post("/generate", response_model=ApiEnvelope[dict[str, str]])
async def generate_report(
    background_tasks: BackgroundTasks,
    workbook_date: date | None = Query(
        None, description="Legacy: single invoice date (same as date_from=date_to)"
    ),
    date_from: date | None = Query(None, description="Inclusive start of invoice date range"),
    date_to: date | None = Query(None, description="Inclusive end of invoice date range"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, str]]:
    """Build or refresh the output workbook from current database state."""
    d_from, d_to = _resolve_date_filter(workbook_date, date_from, date_to)
    try:
        path = await write_workbook(
            db,
            ctx.tenant_id,
            date_from=d_from,
            date_to=d_to,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(_upload_workbook_blob, ctx.tenant_id, path)
    return ApiEnvelope(data={"path": str(path), "filename": path.name})


@router.get("/download")
async def download_report(
    workbook_date: date | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    ctx: AuthContext = Depends(get_auth_context),
) -> FileResponse:
    """Download the generated workbook file."""
    d_from, d_to = _resolve_date_filter(workbook_date, date_from, date_to)
    path = _reports_dir(ctx.tenant_id) / workbook_filename(ctx.tenant_slug, d_from, d_to)

    if not path.is_file():
        legacy = Path(get_settings().upload_dir) / "reports" / path.name
        if legacy.is_file():
            path = legacy
        else:
            raise HTTPException(
                404,
                "Workbook not found. Run POST /api/reports/generate first.",
            )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )
