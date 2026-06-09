"""Vault folder paths — org → vendor → year → month → file (matches Vault UI)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services import blob_storage
from app.services.vendor_resolver import UNKNOWN_SLUG

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

VAULT_ROOT = "invoice"
REJECTED_ROOT = "rejected"


def slug_to_pascal(slug: str) -> str:
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Organisation"


def slug_to_title(slug: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in slug.split("-") if part)


def vault_org_folder(org_slug: str, org_name: str | None = None) -> str:
    if org_slug and org_slug.strip():
        return slug_to_pascal(org_slug)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", org_name or "Organisation").strip("_")
    return cleaned or "Organisation"


def vault_vendor_folder(
    vendor_name: str | None,
    storage_vendor_slug: str | None = None,
) -> str:
    display = (vendor_name or "").strip()
    if display:
        cleaned = re.sub(r'[/\\:*?"<>|]+', "", display).strip()
        return cleaned or "Unknown"
    if storage_vendor_slug and storage_vendor_slug != UNKNOWN_SLUG:
        return slug_to_title(storage_vendor_slug)
    return "Unknown"


def vault_year(invoice_date: date | str | None) -> str:
    if invoice_date is None:
        return "Unknown"
    if isinstance(invoice_date, date):
        return str(invoice_date.year)
    year = str(invoice_date)[:4]
    return year if re.fullmatch(r"\d{4}", year) else "Unknown"


def vault_month(invoice_date: date | str | None) -> str:
    if invoice_date is None:
        return "Unknown"
    if isinstance(invoice_date, date):
        return MONTH_NAMES[invoice_date.month - 1]
    try:
        parsed = datetime.strptime(str(invoice_date)[:10], "%Y-%m-%d")
        return MONTH_NAMES[parsed.month - 1]
    except ValueError:
        return "Unknown"


def vault_doc_number(invoice_no: str | None, invoice_id: int) -> str:
    doc_no = (invoice_no or "").strip() or f"INV-{invoice_id:03d}"
    return re.sub(r"[^a-zA-Z0-9-]+", "-", doc_no)


def vault_file_name(
    invoice_no: str | None,
    invoice_id: int,
    invoice_date: date | str | None,
    original_filename: str,
) -> str:
    doc_no = vault_doc_number(invoice_no, invoice_id)
    if isinstance(invoice_date, date):
        date_part = invoice_date.isoformat()
    elif invoice_date:
        date_part = str(invoice_date)[:10]
    else:
        date_part = "undated"
    suffix = Path(original_filename).suffix.lower()
    if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".docx"}:
        suffix = ".pdf"
    return f"{doc_no}_{date_part}{suffix}"


def build_vault_blob_name(
    org_slug: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
) -> str:
    """Azure blob path: invoice/{org}/{vendor}/{year}/{month}/{file}."""
    return _build_storage_blob_name(
        VAULT_ROOT,
        org_slug,
        org_name=org_name,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
    )


def build_rejected_blob_name(
    org_slug: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
) -> str:
    """Azure blob path: rejected/{org}/{vendor}/{year}/{month}/{file}."""
    return _build_storage_blob_name(
        REJECTED_ROOT,
        org_slug,
        org_name=org_name,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
    )


def _build_storage_blob_name(
    root: str,
    org_slug: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
) -> str:
    org = vault_org_folder(org_slug, org_name)
    vendor = vault_vendor_folder(vendor_name, storage_vendor_slug)
    year = vault_year(invoice_date)
    month = vault_month(invoice_date)
    file_name = vault_file_name(invoice_no, invoice_id, invoice_date, original_filename)
    return f"{root}/{org}/{vendor}/{year}/{month}/{file_name}"


def build_virtual_path(
    org_slug: str,
    *,
    org_name: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
) -> str:
    return build_vault_blob_name(
        org_slug,
        org_name=org_name,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
    )


def filename_from_stored(stored: str | None) -> str:
    if not stored:
        return "invoice.pdf"
    blob_name = stored
    if stored.startswith(blob_storage.BLOB_URI_PREFIX):
        parsed = blob_storage.parse_stored_uri(stored)
        if parsed:
            blob_name = parsed[1]
    if "/" in blob_name:
        return blob_name.rsplit("/", 1)[-1]
    marker_match = re.search(r"_\d+_[a-f0-9]{8}_(.+)$", blob_name)
    if marker_match:
        return marker_match.group(1)
    return Path(blob_name).name or "invoice.pdf"


def _month_sort_index(name: str) -> int:
    try:
        return MONTH_NAMES.index(name)  # type: ignore[arg-type]
    except ValueError:
        return 999


def build_vault_tree(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build org → vendor → year → month tree from vault entry dicts."""
    org_map: dict[str, dict[str, dict[str, dict[str, int]]]] = {}

    for entry in entries:
        org = entry["org"]
        vendor = entry["vendor"]
        year = entry["year"]
        month = entry["month"]
        org_map.setdefault(org, {}).setdefault(vendor, {}).setdefault(year, {})
        org_map[org][vendor][year][month] = org_map[org][vendor][year].get(month, 0) + 1

    tree: list[dict[str, Any]] = []
    for org, vendors in org_map.items():
        org_count = sum(1 for e in entries if e["org"] == org)
        vendor_nodes: list[dict[str, Any]] = []
        for vendor, years in sorted(vendors.items()):
            vendor_count = sum(
                1 for e in entries if e["org"] == org and e["vendor"] == vendor
            )
            year_nodes: list[dict[str, Any]] = []
            for year, months in sorted(years.items(), key=lambda item: item[0], reverse=True):
                year_count = sum(
                    1
                    for e in entries
                    if e["org"] == org and e["vendor"] == vendor and e["year"] == year
                )
                month_nodes = [
                    {
                        "id": f"{org}/{vendor}/{year}/{month}",
                        "label": month,
                        "kind": "month",
                        "count": count,
                        "children": [],
                    }
                    for month, count in sorted(
                        months.items(), key=lambda item: _month_sort_index(item[0])
                    )
                ]
                year_nodes.append(
                    {
                        "id": f"{org}/{vendor}/{year}",
                        "label": year,
                        "kind": "year",
                        "count": year_count,
                        "children": month_nodes,
                    }
                )
            vendor_nodes.append(
                {
                    "id": f"{org}/{vendor}",
                    "label": vendor,
                    "kind": "vendor",
                    "count": vendor_count,
                    "children": year_nodes,
                }
            )
        tree.append(
            {
                "id": org,
                "label": org,
                "kind": "org",
                "count": org_count,
                "children": vendor_nodes,
            }
        )
    return tree
