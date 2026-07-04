"""Workbook generation and download helpers for reports API."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from app.services.shared import blob_storage
from app.services.tenant.tenant_storage_paths import tenant_blob_name, tenant_local_dir
from app.services.reports.workbook_writer import workbook_filename
from app.utils.logger import get_logger

logger = get_logger(__name__)


def reports_dir(tenant_id: uuid.UUID) -> Path:
    return tenant_local_dir(tenant_id, "reports")


def resolve_workbook_date_filter(
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
        raise ValueError("date_from must be on or before date_to")
    return date_from, date_to


def workbook_path(
    tenant_id: uuid.UUID,
    tenant_slug: str,
    *,
    date_from: date | None,
    date_to: date | None,
) -> Path:
    return reports_dir(tenant_id) / workbook_filename(tenant_slug, date_from, date_to)


def upload_workbook_blob(tenant_id: uuid.UUID, path: Path) -> None:
    """Upload workbook to blob storage without blocking the HTTP response."""
    if not blob_storage.is_blob_enabled():
        return
    try:
        blob_name = tenant_blob_name(tenant_id, f"reports/{path.name}")
        blob_storage.upload_bytes(blob_name, path.read_bytes())
        logger.info("workbook_uploaded_blob", blob_name=blob_name)
    except Exception as exc:
        logger.warning("workbook_blob_upload_failed", path=str(path), error=str(exc))
