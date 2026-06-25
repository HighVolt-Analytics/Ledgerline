"""Azure Blob Storage for invoice PDFs."""

from __future__ import annotations

import uuid
from datetime import date

from app.config import get_settings
from app.services import vault_paths
from app.services.tenant_storage_paths import (
    is_legacy_blob_path,
    legacy_to_tenant_path,
    tenant_root,
)
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
    day=None,
) -> str:
    """Build tenant-scoped vault blob path."""
    _ = (file_hash, day)
    return vault_paths.build_vault_blob_name(
        tenant_id,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
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


def blob_exists_for_name(blob_name: str) -> bool:
    try:
        settings = get_settings()
        client = _service_client()
        blob = client.get_blob_client(settings.azure_storage_container, blob_name)
        blob.get_blob_properties()
        return True
    except Exception:
        return False


def blob_exists(stored: str) -> bool:
    parsed = parse_stored_uri(stored)
    if parsed is None:
        return False
    _, blob_name = parsed
    return blob_exists_for_name(blob_name)


def download_bytes_for_name(blob_name: str) -> bytes:
    settings = get_settings()
    client = _service_client()
    blob = client.get_blob_client(settings.azure_storage_container, blob_name)
    try:
        return blob.download_blob().readall()
    except Exception as exc:
        if "BlobNotFound" in str(exc) or exc.__class__.__name__ == "ResourceNotFoundError":
            raise FileNotFoundError(blob_name) from exc
        raise


def download_bytes(stored: str) -> bytes:
    parsed = parse_stored_uri(stored)
    if parsed is None:
        raise FileNotFoundError(stored)
    _, blob_name = parsed
    return download_bytes_for_name(blob_name)


def delete_blob(stored: str) -> bool:
    """Delete blob if it exists. Returns True when a blob was removed."""
    parsed = parse_stored_uri(stored)
    if parsed is None:
        return False
    _, blob_name = parsed
    try:
        settings = get_settings()
        client = _service_client()
        blob = client.get_blob_client(settings.azure_storage_container, blob_name)
        blob.delete_blob()
        logger.info("blob_deleted", blob_name=blob_name)
        return True
    except Exception:
        return False


def _invoice_blob_marker(invoice_id: int) -> str:
    return f"INV-{invoice_id}"


def _blob_name_matches_invoice(blob_name: str, invoice_id: int) -> bool:
    filename = blob_name.rsplit("/", 1)[-1]
    marker = _invoice_blob_marker(invoice_id)
    if filename.startswith(f"{marker}_") or filename.startswith(f"{marker}."):
        return True
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.endswith(f"_id{invoice_id}")


def _search_prefix_for_invoice(
    container,
    prefix: str,
    invoice_id: int,
) -> str | None:
    try:
        for blob in container.list_blobs(name_starts_with=prefix):
            if _blob_name_matches_invoice(blob.name, invoice_id):
                return to_stored_uri(blob.name)
    except Exception:
        return None
    return None


def find_blob_uri_for_invoice(
    invoice_id: int,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
    include_legacy: bool = True,
    prefer_rejected: bool = False,
) -> str | None:
    """Locate a relocated invoice blob when raw_file_path is stale (tenant-scoped)."""
    if not is_blob_enabled():
        return None
    settings = get_settings()
    client = _service_client()
    container = client.get_container_client(settings.azure_storage_container)

    prefixes: list[str] = []
    tenant_invoice = f"{tenant_root(tenant_id)}/invoice/"
    tenant_rejected = f"{tenant_root(tenant_id)}/rejected/"
    if prefer_rejected:
        prefixes.extend([tenant_rejected, tenant_invoice])
    else:
        prefixes.extend([tenant_invoice, tenant_rejected])
    if tenant_slug:
        org_folder = vault_paths.vault_tenant_folder(tenant_slug, tenant_name)
        prefixes.append(f"{tenant_root(tenant_id)}/invoice/{org_folder}/")

    seen: set[str] = set()
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        found = _search_prefix_for_invoice(container, prefix, invoice_id)
        if found:
            return found

    if not include_legacy:
        return None

    legacy_prefixes: list[str] = []
    if tenant_slug:
        org_folder = vault_paths.vault_tenant_folder(tenant_slug, tenant_name)
        legacy_prefixes.append(f"invoice/{org_folder}/")
    if prefer_rejected:
        legacy_prefixes.append("rejected/")
        legacy_prefixes.append("invoice/")
    else:
        legacy_prefixes.append("invoice/")
        legacy_prefixes.append("rejected/")

    for prefix in legacy_prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        found = _search_prefix_for_invoice(container, prefix, invoice_id)
        if found:
            parsed = parse_stored_uri(found)
            if parsed and is_legacy_blob_path(parsed[1]):
                return to_stored_uri(legacy_to_tenant_path(tenant_id, parsed[1]))
            return found
    return None


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
    _wait_for_blob_copy(dest)
    source.delete_blob()
    new_uri = to_stored_uri(new_blob_name)
    logger.info("blob_moved", from_blob=old_name, to_blob=new_blob_name)
    return new_uri


def _wait_for_blob_copy(dest, timeout_s: float = 30.0) -> None:
    """Block until async server-side copy completes (delete source only after this)."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        props = dest.get_blob_properties()
        copy = getattr(props, "copy", None)
        status = getattr(copy, "status", None) if copy is not None else None
        if status == "success":
            return
        if status == "failed":
            detail = getattr(copy, "status_description", "") if copy is not None else ""
            raise OSError(f"Blob copy failed: {detail or status}")
        time.sleep(0.2)
    raise TimeoutError("Blob copy timed out")
