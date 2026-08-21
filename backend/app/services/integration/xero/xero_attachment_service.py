"""Upload original invoice PDF to a Xero invoice attachment endpoint."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.integration.xero.xero_client import XeroApiError, XeroClient
from app.services.shared.file_storage import open_pdf_for_reading
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MiB
ALLOWED_MIME = {"application/pdf"}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()]+", "_", (name or "invoice.pdf").strip())
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:180] or "invoice.pdf"


async def upload_invoice_pdf_attachment(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
    xero_invoice_id: str,
    storage_locator: str,
    filename: str,
) -> dict[str, Any]:
    """Retrieve PDF via secure storage abstraction and PUT to Xero Attachments."""
    settings = get_settings()
    del settings  # reserved for future size/mime config overrides

    safe_name = _safe_filename(filename)
    try:
        with open_pdf_for_reading(storage_locator, tenant_id=tenant_id) as path:
            data = Path(path).read_bytes()
    except FileNotFoundError as exc:
        raise XeroApiError(
            status_code=404,
            error_code="attachment_missing",
            message="Source PDF was not found in secure storage",
        ) from exc

    if not data:
        raise XeroApiError(
            status_code=400,
            error_code="invalid_payload",
            message="Source PDF is empty",
        )
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise XeroApiError(
            status_code=400,
            error_code="invalid_payload",
            message=f"PDF exceeds maximum size of {MAX_ATTACHMENT_BYTES} bytes",
        )
    # PDF magic header check
    if not data.startswith(b"%PDF"):
        raise XeroApiError(
            status_code=400,
            error_code="invalid_payload",
            message="Attachment MIME type must be application/pdf",
        )

    client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    path = f"Invoices/{xero_invoice_id}/Attachments/{safe_name}"
    response = await client.put_bytes(
        path,
        content=data,
        content_type="application/pdf",
        params={"IncludeOnline": "true"},
    )
    payload = response.json() if response.content else {}
    attachments = payload.get("Attachments") or []
    attachment_id = None
    if attachments and isinstance(attachments[0], dict):
        attachment_id = attachments[0].get("AttachmentID") or attachments[0].get("FileName")
    logger.info(
        "xero_attachment_uploaded",
        tenant_id=str(tenant_id),
        xero_invoice_id=xero_invoice_id,
        filename=safe_name,
        size=len(data),
    )
    return {
        "attachment_id": str(attachment_id) if attachment_id else None,
        "filename": safe_name,
        "size_bytes": len(data),
        "mime_type": "application/pdf",
    }
