"""Store and read invoice PDFs (local disk or Azure Blob)."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from app.config import get_settings
from app.services import blob_storage, vault_paths
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _local_vault_path(blob_name: str) -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / blob_name


def store_invoice_pdf(
    data: bytes,
    org_slug: str,
    vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
) -> str:
    blob_name = blob_storage.build_blob_name(
        org_slug,
        vendor_slug,
        invoice_id,
        file_hash,
        filename,
        org_name=org_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
    )

    if blob_storage.is_blob_enabled():
        return blob_storage.upload_bytes(blob_name, data)

    dest = _local_vault_path(blob_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info("pdf_saved_local", path=str(dest))
    return str(dest)


def relocate_stored_pdf(stored_path: str, new_blob_name: str) -> str:
    """Move a stored PDF/blob to an absolute vault or rejected blob path."""
    if blob_storage.is_blob_enabled() and stored_path.startswith(blob_storage.BLOB_URI_PREFIX):
        parsed = blob_storage.parse_stored_uri(stored_path)
        if parsed and parsed[1] == new_blob_name:
            return stored_path
        return blob_storage.move_blob(stored_path, new_blob_name)

    new_dest = _local_vault_path(new_blob_name)
    if stored_path == str(new_dest):
        return stored_path

    old = Path(stored_path)
    if old.is_file():
        new_dest.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new_dest)
        return str(new_dest)
    return stored_path


def relocate_invoice_to_rejected(
    stored_path: str,
    org_slug: str,
    invoice_id: int,
    filename: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
) -> str:
    new_name = vault_paths.build_rejected_blob_name(
        org_slug,
        org_name=org_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=filename,
    )
    return relocate_stored_pdf(stored_path, new_name)


def relocate_rejected_to_vault(
    stored_path: str,
    org_slug: str,
    vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
) -> str:
    _ = file_hash
    new_name = blob_storage.build_blob_name(
        org_slug,
        vendor_slug,
        invoice_id,
        file_hash,
        filename,
        org_name=org_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
    )
    return relocate_stored_pdf(stored_path, new_name)


def relocate_invoice_pdf(
    stored_path: str,
    org_slug: str,
    new_vendor_slug: str,
    invoice_id: int,
    file_hash: str,
    filename: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    route_target: str | None = None,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
) -> str:
    new_name = blob_storage.build_blob_name(
        org_slug,
        new_vendor_slug,
        invoice_id,
        file_hash,
        filename,
        org_name=org_name,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        route_target=route_target,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
    )
    return relocate_stored_pdf(stored_path, new_name)


def _suffix_from_stored(stored_path: str) -> str:
    name = vault_paths.filename_from_stored(stored_path)
    return Path(name).suffix.lower() or ".pdf"


@contextmanager
def open_pdf_for_reading(stored_path: str) -> Iterator[Path]:
    """Download or open a stored invoice attachment for parsing."""
    suffix = _suffix_from_stored(stored_path)
    if blob_storage.is_blob_enabled() and stored_path.startswith(
        blob_storage.BLOB_URI_PREFIX
    ):
        data = blob_storage.download_bytes(stored_path)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            yield tmp_path
        finally:
            tmp_path.unlink(missing_ok=True)
        return

    path = Path(stored_path)
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


def stored_file_available(stored_path: str | None) -> bool:
    """True if raw_file_path is set and the blob or local file exists."""
    if not has_stored_path(stored_path):
        return False
    if blob_storage.is_blob_enabled() and stored_path.startswith(
        blob_storage.BLOB_URI_PREFIX
    ):
        return blob_storage.blob_exists(stored_path)
    return Path(stored_path).is_file()


def delete_stored_file(stored_path: str | None) -> None:
    """Remove the stored PDF from blob storage or local disk when present."""
    if not stored_path or not stored_path.strip():
        return
    if blob_storage.is_blob_enabled() and stored_path.startswith(
        blob_storage.BLOB_URI_PREFIX
    ):
        blob_storage.delete_blob(stored_path)
        return
    path = Path(stored_path)
    if path.is_file():
        path.unlink()
        logger.info("pdf_deleted_local", path=str(path))


def read_invoice_file(stored_path: str) -> tuple[bytes, str, str]:
    """Return file bytes, media type, and suggested download filename."""
    suffix = _suffix_from_stored(stored_path)
    media_type, default_name = _MEDIA_BY_SUFFIX.get(
        suffix, ("application/octet-stream", "invoice.bin")
    )

    if blob_storage.is_blob_enabled() and stored_path.startswith(
        blob_storage.BLOB_URI_PREFIX
    ):
        data = blob_storage.download_bytes(stored_path)
        name = vault_paths.filename_from_stored(stored_path)
        return data, media_type, name or default_name

    path = Path(stored_path)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    return path.read_bytes(), media_type, path.name or default_name
