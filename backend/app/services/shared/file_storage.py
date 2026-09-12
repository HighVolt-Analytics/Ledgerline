"""Store and read invoice PDFs (local disk or Azure Blob)."""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from app.config import get_settings
from app.services.shared import blob_storage
from app.services.vault import vault_paths
from app.services.tenant.tenant_storage_paths import (
    blob_name_from_stored,
    resolve_blob_candidates,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _local_vault_path(blob_name: str) -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / blob_name


def _stored_uri_for_blob_name(blob_name: str) -> str:
    if blob_storage.is_blob_enabled():
        return blob_storage.to_stored_uri(blob_name)
    return str(_local_vault_path(blob_name))


def _resolve_readable_stored(
    stored_path: str | None,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> str | None:
    """Return first stored path / blob name that exists (supports legacy layouts)."""
    if not stored_path or not stored_path.strip():
        return None

    candidate_args = {
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "tenant_name": tenant_name,
    }

    if blob_storage.is_blob_enabled() and stored_path.startswith(blob_storage.BLOB_URI_PREFIX):
        for name in resolve_blob_candidates(stored_path, **candidate_args):
            uri = blob_storage.to_stored_uri(name)
            if blob_storage.blob_exists(uri):
                return uri
        return None

    candidates: list[Path] = []
    seen: set[str] = set()
    for name in resolve_blob_candidates(stored_path, **candidate_args):
        path = _local_vault_path(name)
        key = str(path)
        if key not in seen:
            seen.add(key)
            candidates.append(path)
    raw = Path(stored_path)
    if str(raw) not in seen:
        candidates.append(raw)

    for path in candidates:
        if path.is_file():
            if blob_storage.is_blob_enabled():
                return blob_storage.to_stored_uri(blob_name_from_stored(str(path)) or path.name)
            return str(path)
    return None


def is_rejected_storage_path(stored_path: str | None) -> bool:
    """True when the stored URI/path is under rejected/ (invoice/ vs rejected/ layout)."""
    if not stored_path:
        return False
    if _is_rejected_blob_name(stored_path):
        return True
    return _is_rejected_blob_name(blob_name_from_stored(stored_path))


def resolve_readable_stored(
    stored_path: str | None,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> str | None:
    """Return the first stored path / blob URI that exists for this invoice file."""
    return _resolve_readable_stored(
        stored_path,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )


def _is_rejected_blob_name(name: str | None) -> bool:
    if not name:
        return False
    return "rejected" in name.strip().lstrip("/").replace("\\", "/").split("/")


def store_invoice_pdf(
    data: bytes,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    tenant_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    blob_name = blob_storage.build_blob_name(
        tenant_id,
        tenant_slug,
        vendor_slug,
        invoice_id,
        file_hash,
        filename,
        tenant_name=tenant_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
        unique_timestamp=True,
    )

    if blob_storage.is_blob_enabled():
        return blob_storage.upload_bytes(blob_name, data)

    dest = _local_vault_path(blob_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info("pdf_saved_local", path=str(dest))
    return str(dest)


def relocate_stored_pdf(
    stored_path: str,
    new_blob_name: str,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> str:
    """Move a stored PDF/blob to an absolute vault or rejected blob path."""
    resolved = (
        _resolve_readable_stored(
            stored_path,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
        )
        or stored_path
    )
    if blob_storage.is_blob_enabled() and resolved.startswith(blob_storage.BLOB_URI_PREFIX):
        parsed = blob_storage.parse_stored_uri(resolved)
        if parsed and parsed[1] == new_blob_name:
            return resolved
        return blob_storage.move_blob(resolved, new_blob_name)

    new_dest = _local_vault_path(new_blob_name)
    if resolved == str(new_dest):
        return resolved

    old = Path(resolved)
    if old.is_file():
        new_dest.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new_dest)
        return str(new_dest)
    return resolved


def relocate_invoice_to_rejected(
    stored_path: str,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    invoice_id: int,
    filename: str,
    *,
    tenant_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    new_name = vault_paths.build_rejected_blob_name(
        tenant_id,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=filename,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
    )
    resolved = _resolve_readable_stored(
        stored_path,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )
    if not resolved:
        return stored_path
    source_name = blob_name_from_stored(resolved)
    if source_name == new_name:
        return resolved
    if _is_rejected_blob_name(source_name):
        return resolved
    return relocate_stored_pdf(
        resolved,
        new_name,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )


def relocate_rejected_to_vault(
    stored_path: str,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    tenant_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    new_name = blob_storage.build_blob_name(
        tenant_id,
        tenant_slug,
        vendor_slug,
        invoice_id,
        file_hash,
        filename,
        tenant_name=tenant_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
    )
    return relocate_stored_pdf(
        stored_path,
        new_name,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )


def relocate_invoice_pdf(
    stored_path: str,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    new_vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    tenant_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    new_name = blob_storage.build_blob_name(
        tenant_id,
        tenant_slug,
        new_vendor_slug,
        invoice_id,
        file_hash,
        filename,
        tenant_name=tenant_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
    )
    return relocate_stored_pdf(
        stored_path,
        new_name,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
    )


def _suffix_from_stored(stored_path: str) -> str:
    name = vault_paths.filename_from_stored(stored_path)
    return Path(name).suffix.lower() or ".pdf"


@contextmanager
def open_pdf_for_reading(
    stored_path: str,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
) -> Iterator[Path]:
    """Download or open a stored invoice attachment for parsing."""
    resolved = _resolve_readable_stored(stored_path, tenant_id=tenant_id)
    if resolved is None:
        raise FileNotFoundError(stored_path)

    suffix = _suffix_from_stored(resolved)
    if blob_storage.is_blob_enabled() and resolved.startswith(blob_storage.BLOB_URI_PREFIX):
        data = blob_storage.download_bytes(resolved)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            yield tmp_path
        finally:
            tmp_path.unlink(missing_ok=True)
        return

    path = Path(resolved)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    yield path


_MEDIA_BY_SUFFIX: dict[str, tuple[str, str]] = {
    ".pdf": ("application/pdf", "invoice.pdf"),
    ".jpg": ("image/jpeg", "invoice.jpg"),
    ".jpeg": ("image/jpeg", "invoice.jpeg"),
    ".png": ("image/png", "invoice.png"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "invoice.docx",
    ),
}


def has_stored_path(stored_path: str | None) -> bool:
    """Fast check: a storage path is recorded (no remote blob/disk round-trip)."""
    return bool(stored_path and stored_path.strip())


def stored_file_available(
    stored_path: str | None,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> bool:
    """True if raw_file_path is set and the blob or local file exists."""
    return (
        _resolve_readable_stored(
            stored_path,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
        )
        is not None
    )


def _parse_audit_relocate_detail(detail: object) -> dict:
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            detail = {}
    return detail if isinstance(detail, dict) else {}


def _lookup_repaired_stored_path(
    *,
    invoice_id: int,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    raw_file_path: str | None,
    invoice_status,
    audit_relocate_details: list[dict],
    storage_kwargs: dict,
) -> tuple[str | None, str | None]:
    """Resolve a stale raw_file_path via audit history or blob search (sync; use in thread)."""
    from app.models.invoice import InvoiceStatus

    if stored_file_available(raw_file_path, **storage_kwargs):
        return None, None

    for detail in audit_relocate_details:
        resolved = _resolve_readable_stored(detail.get("to_path"), **storage_kwargs)
        if resolved:
            return resolved, "audit"

    prefer_rejected = (
        invoice_status == InvoiceStatus.REJECTED
        or is_rejected_storage_path(raw_file_path)
    )
    found = blob_storage.find_blob_uri_for_invoice(
        invoice_id,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        prefer_rejected=prefer_rejected,
    )
    if found and stored_file_available(found, **storage_kwargs):
        return found, "blob_search"
    return None, None


async def repair_invoice_stored_path(session, invoice) -> bool:
    """
    Recover raw_file_path when the blob was relocated but the DB row was not updated.

    Returns True when raw_file_path was repaired to an existing blob/file.
    """
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.tenant import Tenant
    from app.services.audit.audit_service import log_event

    org = await session.get(Tenant, invoice.tenant_id)
    tenant_slug = org.slug if org else get_settings().default_tenant_slug
    tenant_name = org.name if org else None
    storage_kwargs = {
        "tenant_id": invoice.tenant_id,
        "tenant_slug": tenant_slug,
        "tenant_name": tenant_name,
    }

    if await asyncio.to_thread(
        stored_file_available, invoice.raw_file_path, **storage_kwargs
    ):
        return False

    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice.id,
                AuditLog.event == "blob_relocated",
            )
            .order_by(AuditLog.id.desc())
            .limit(10)
        )
    ).scalars().all()
    audit_details = [_parse_audit_relocate_detail(row.detail) for row in rows]

    resolved, source = await asyncio.to_thread(
        _lookup_repaired_stored_path,
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        raw_file_path=invoice.raw_file_path,
        invoice_status=invoice.status,
        audit_relocate_details=audit_details,
        storage_kwargs=storage_kwargs,
    )
    if resolved and source:
        old_path = invoice.raw_file_path
        invoice.raw_file_path = resolved
        await log_event(
            session,
            "blob_path_repaired",
            invoice_id=invoice.id,
            detail={"from_path": old_path, "to_path": resolved, "source": source},
        )
        return True

    return False


async def ensure_invoice_stored_file(session, invoice) -> None:
    """
    Repair raw_file_path and locate the stored PDF before approve/reprocess/download.

    Raises ValueError when no blob or local file can be resolved — unless the
    invoice is an intentional without-document / manual-entry capture.
    """
    from app.services.invoice.processing_override_catalog import (
        allows_approval_without_stored_file,
    )

    if allows_approval_without_stored_file(invoice):
        return

    await repair_invoice_stored_path(session, invoice)
    if await asyncio.to_thread(
        stored_file_available, invoice.raw_file_path, tenant_id=invoice.tenant_id
    ):
        return

    raise ValueError(
        "Invoice has no stored file. "
        f"Upload via POST /api/invoices/{invoice.id}/attach first."
    )


# Backwards-compatible alias used by approvals flow.
ensure_stored_file_for_approval = ensure_invoice_stored_file


def delete_stored_file(
    stored_path: str | None,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
    invoice_id: int | None = None,
    prefer_rejected: bool = False,
) -> None:
    """Remove the stored PDF from blob storage or local disk when present."""
    if not stored_path and invoice_id is None:
        return

    deleted: set[str] = set()

    def _delete_one(path: str | None) -> None:
        if not path or not path.strip():
            return
        resolved = (
            _resolve_readable_stored(
                path,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
            )
            or path
        )
        if resolved in deleted:
            return
        deleted.add(resolved)
        if blob_storage.is_blob_enabled() and resolved.startswith(blob_storage.BLOB_URI_PREFIX):
            blob_storage.delete_blob(resolved)
            return
        local = Path(resolved)
        if local.is_file():
            local.unlink()
            logger.info("pdf_deleted_local", path=str(local))

    _delete_one(stored_path)

    if invoice_id is not None and tenant_id is not None and blob_storage.is_blob_enabled():
        found = blob_storage.find_blob_uri_for_invoice(
            invoice_id,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            prefer_rejected=prefer_rejected,
        )
        _delete_one(found)


def read_invoice_file(
    stored_path: str,
    *,
    tenant_id: uuid.UUID | int | str | None = None,
) -> tuple[bytes, str, str]:
    """Return file bytes, media type, and suggested download filename."""
    resolved = _resolve_readable_stored(stored_path, tenant_id=tenant_id)
    if resolved is None:
        raise FileNotFoundError(stored_path)

    suffix = _suffix_from_stored(resolved)
    media_type, default_name = _MEDIA_BY_SUFFIX.get(
        suffix, ("application/octet-stream", "invoice.bin")
    )

    if blob_storage.is_blob_enabled() and resolved.startswith(blob_storage.BLOB_URI_PREFIX):
        data = blob_storage.download_bytes(resolved)
        name = vault_paths.filename_from_stored(resolved)
        return data, media_type, name or default_name

    path = Path(resolved)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    return path.read_bytes(), media_type, path.name or default_name
