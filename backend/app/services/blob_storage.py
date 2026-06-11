"""Azure Blob Storage for invoice PDFs."""

from __future__ import annotations

from datetime import date

from app.config import get_settings
from app.services import vault_paths
from app.utils.logger import get_logger

logger = get_logger(__name__)

BLOB_URI_PREFIX = "azureblob://"


def is_blob_enabled() -> bool:
    return get_settings().blob_enabled


def _service_client():
    from azure.storage.blob import BlobServiceClient

    settings = get_settings()
    return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)


def _ensure_container() -> None:
    settings = get_settings()
    client = _service_client()
    try:
        client.create_container(settings.azure_storage_container)
    except Exception:
        pass


def build_blob_name(
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
    day=None,
) -> str:
    """Build vault blob path: invoice/{org}/{book}/{vendor}/{year}/{month}/{file}."""
    _ = (file_hash, day)
    return vault_paths.build_vault_blob_name(
        org_slug,
        org_name=org_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
    )


def to_stored_uri(blob_name: str) -> str:
    settings = get_settings()
    return f"{BLOB_URI_PREFIX}{settings.azure_storage_container}/{blob_name}"


def parse_stored_uri(stored: str) -> tuple[str, str] | None:
    if not stored.startswith(BLOB_URI_PREFIX):
        return None
    rest = stored[len(BLOB_URI_PREFIX) :]
    container, _, blob_name = rest.partition("/")
    if not container or not blob_name:
        return None
    return container, blob_name


def upload_bytes(blob_name: str, data: bytes) -> str:
    settings = get_settings()
    _ensure_container()
    client = _service_client()
    blob = client.get_blob_client(settings.azure_storage_container, blob_name)
    blob.upload_blob(data, overwrite=True)
    uri = to_stored_uri(blob_name)
    logger.info("blob_uploaded", blob_name=blob_name, bytes=len(data))
    return uri


def blob_exists(stored: str) -> bool:
    parsed = parse_stored_uri(stored)
    if parsed is None:
        return False
    container, blob_name = parsed
    try:
        client = _service_client()
        blob = client.get_blob_client(container, blob_name)
        blob.get_blob_properties()
        return True
    except Exception:
        return False


def download_bytes(stored: str) -> bytes:
    parsed = parse_stored_uri(stored)
    if parsed is None:
        raise FileNotFoundError(stored)
    container, blob_name = parsed
    client = _service_client()
    blob = client.get_blob_client(container, blob_name)
    return blob.download_blob().readall()


def delete_blob(stored: str) -> bool:
    """Delete blob if it exists. Returns True when a blob was removed."""
    parsed = parse_stored_uri(stored)
    if parsed is None:
        return False
    container, blob_name = parsed
    try:
        client = _service_client()
        blob = client.get_blob_client(container, blob_name)
        blob.delete_blob()
        logger.info("blob_deleted", blob_name=blob_name)
        return True
    except Exception:
        return False


def move_blob(stored: str, new_blob_name: str) -> str:
    parsed = parse_stored_uri(stored)
    if parsed is None:
        raise FileNotFoundError(stored)
    container, old_name = parsed
    if old_name == new_blob_name:
        return stored
    settings = get_settings()
    client = _service_client()
    source = client.get_blob_client(container, old_name)
    dest = client.get_blob_client(settings.azure_storage_container, new_blob_name)
    dest.start_copy_from_url(source.url)
    source.delete_blob()
    new_uri = to_stored_uri(new_blob_name)
    logger.info("blob_moved", from_blob=old_name, to_blob=new_blob_name)
    return new_uri
