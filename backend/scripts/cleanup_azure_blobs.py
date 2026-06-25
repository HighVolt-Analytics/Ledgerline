"""Remove Azure blob containers and paths not used by the backend."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.invoice import Invoice
from app.services import blob_storage
from app.services.tenant_storage_paths import blob_name_from_stored, is_legacy_blob_path

# Only the `invoices` container is configured in the backend.
UNUSED_CONTAINERS = ("exports", "incoming-pdfs", "processed")

# Inside container: tenant-prefixed vault/reports; legacy roots optional after migration.
UNUSED_BLOB_PREFIXES = ("_healthcheck/", "hv-org/")


def _service_client():
    from azure.storage.blob import BlobServiceClient

    settings = get_settings()
    return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)


async def _referenced_blob_names() -> set[str]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Invoice.raw_file_path).where(Invoice.raw_file_path.isnot(None))
            )
        ).scalars().all()
    keep: set[str] = set()
    for stored in rows:
        name = blob_name_from_stored(stored)
        if name:
            keep.add(name)
    return keep


def clear_legacy_prefix_blobs(*, dry_run: bool = False) -> int:
    """Delete pre-migration root blobs (invoice/, rejected/, reports/) not in DB."""
    if not blob_storage.is_blob_enabled():
        print("blob storage disabled — nothing to clear")
        return 0

    keep = asyncio.run(_referenced_blob_names())
    settings = get_settings()
    client = _service_client()
    container = client.get_container_client(settings.azure_storage_container)

    to_delete: list[str] = []
    for blob in container.list_blobs():
        if blob.name in keep:
            continue
        if is_legacy_blob_path(blob.name) or blob.name.startswith("reports/"):
            to_delete.append(blob.name)

    if dry_run:
        print(f"would delete {len(to_delete)} legacy/orphan blob(s); keeping {len(keep)}")
        for name in to_delete:
            print(f"  {name}")
        return len(to_delete)

    deleted = 0
    for name in to_delete:
        container.delete_blob(name)
        deleted += 1
        print(f"deleted blob: {name}")
    print(f"removed {deleted} legacy/orphan blob(s); kept {len(keep)} linked to invoices")
    return deleted


def clear_orphan_blobs(*, dry_run: bool = False, include_reports: bool = False) -> int:
    """Delete blobs in the invoices container not referenced by any invoice row."""
    if not blob_storage.is_blob_enabled():
        print("blob storage disabled — nothing to clear")
        return 0

    keep = asyncio.run(_referenced_blob_names())
    settings = get_settings()
    client = _service_client()
    container = client.get_container_client(settings.azure_storage_container)

    to_delete: list[str] = []
    for blob in container.list_blobs():
        if blob.name in keep:
            continue
        if is_legacy_blob_path(blob.name):
            to_delete.append(blob.name)
        elif include_reports and blob.name.startswith("reports/"):
            to_delete.append(blob.name)

    if dry_run:
        print(f"would delete {len(to_delete)} orphan blob(s); keeping {len(keep)}")
        for name in to_delete:
            print(f"  {name}")
        return len(to_delete)

    deleted = 0
    for name in to_delete:
        container.delete_blob(name)
        deleted += 1
        print(f"deleted blob: {name}")
    print(f"removed {deleted} orphan blob(s); kept {len(keep)} linked to invoices")
    return deleted


def clear_reports_prefix(*, dry_run: bool = False) -> int:
    """Delete generated workbook exports under reports/."""
    if not blob_storage.is_blob_enabled():
        print("blob storage disabled — nothing to clear")
        return 0

    settings = get_settings()
    client = _service_client()
    container = client.get_container_client(settings.azure_storage_container)
    names = [b.name for b in container.list_blobs(name_starts_with="reports/")]
    if dry_run:
        print(f"would delete {len(names)} report blob(s)")
        for name in names:
            print(f"  {name}")
        return len(names)

    deleted = 0
    for name in names:
        container.delete_blob(name)
        deleted += 1
        print(f"deleted blob: {name}")
    print(f"cleared {deleted} report blob(s)")
    return deleted


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
        "--orphans",
        action="store_true",
        help="Delete blobs not linked to any invoice.raw_file_path in the database",
    )
    parser.add_argument(
        "--reports",
        action="store_true",
        help="With --orphans, also delete reports/ workbook exports",
    )
    parser.add_argument(
        "--reports-only",
        action="store_true",
        help="Delete only reports/ workbook exports",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Delete legacy invoice/, rejected/, reports/ blobs not referenced in DB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List blobs that would be deleted",
    )
    args = parser.parse_args()
    if args.all:
        clear_invoice_container(dry_run=args.dry_run)
    elif args.orphans:
        clear_orphan_blobs(dry_run=args.dry_run, include_reports=args.reports)
    elif args.reports_only:
        clear_reports_prefix(dry_run=args.dry_run)
    elif args.legacy:
        clear_legacy_prefix_blobs(dry_run=args.dry_run)
    else:
        result = cleanup_unused_blobs()
        print("done", result)
