"""Remove Azure blob containers and paths not used by the backend."""

from __future__ import annotations

import argparse

from app.config import get_settings
from app.services import blob_storage

# Only the `invoices` container is configured in the backend.
UNUSED_CONTAINERS = ("exports", "incoming-pdfs", "processed")

# Inside `invoices`: keep invoice/ (vault) and reports/ (workbooks).
UNUSED_BLOB_PREFIXES = ("_healthcheck/", "hv-org/")


def _service_client():
    from azure.storage.blob import BlobServiceClient

    settings = get_settings()
    return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)


def clear_invoice_container(*, dry_run: bool = False) -> int:
    """Delete every blob in the configured invoices container."""
    if not blob_storage.is_blob_enabled():
        print("blob storage disabled — nothing to clear")
        return 0

    settings = get_settings()
    client = _service_client()
    container = client.get_container_client(settings.azure_storage_container)
    names = [b.name for b in container.list_blobs()]
    if dry_run:
        print(f"would delete {len(names)} blob(s) from {settings.azure_storage_container}")
        for name in names:
            print(f"  {name}")
        return len(names)

    deleted = 0
    for name in names:
        container.delete_blob(name)
        deleted += 1
        print(f"deleted blob: {name}")
    print(f"cleared {deleted} blob(s) from {settings.azure_storage_container}")
    return deleted


def cleanup_unused_blobs() -> dict[str, int]:
    if not blob_storage.is_blob_enabled():
        return {"containers_deleted": 0, "blobs_deleted": 0}

    settings = get_settings()
    client = _service_client()
    blobs_deleted = 0

    container = client.get_container_client(settings.azure_storage_container)
    for blob in container.list_blobs():
        if any(blob.name.startswith(prefix) for prefix in UNUSED_BLOB_PREFIXES):
            container.delete_blob(blob.name)
            blobs_deleted += 1
            print(f"deleted blob: {blob.name}")

    containers_deleted = 0
    for name in UNUSED_CONTAINERS:
        try:
            container_client = client.get_container_client(name)
            if not container_client.exists():
                continue
            for blob in container_client.list_blobs():
                container_client.delete_blob(blob.name)
                blobs_deleted += 1
            container_client.delete_container()
            containers_deleted += 1
            print(f"deleted container: {name}")
        except Exception as exc:
            print(f"skip container {name}: {exc}")

    return {"containers_deleted": containers_deleted, "blobs_deleted": blobs_deleted}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azure blob cleanup utilities")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete every blob in the configured invoices container",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List blobs that would be deleted (with --all)",
    )
    args = parser.parse_args()
    if args.all:
        clear_invoice_container(dry_run=args.dry_run)
    else:
        result = cleanup_unused_blobs()
        print("done", result)
