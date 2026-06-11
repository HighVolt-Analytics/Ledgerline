"""Vault folder paths — org → book → vendor → year → month → file (matches Vault UI)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services import blob_storage
from app.services.vendor_resolver import UNKNOWN_SLUG

ROUTE_PURCHASE = "Purchase Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"
ROUTE_UNROUTED = "Unrouted"

_KNOWN_BOOKS = frozenset(
    {
        ROUTE_PURCHASE,
        ROUTE_EXPENSES,
        ROUTE_TEAM,
        ROUTE_VAULT,
        ROUTE_UNROUTED,
    }
)

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


def vault_book_folder(route_target: str | None) -> str:
    """Route-target book segment under org (architecture §2.1 destinations)."""
    key = (route_target or "").strip()
    if key in _KNOWN_BOOKS and key != ROUTE_UNROUTED:
        return key
    if key:
        cleaned = re.sub(r'[/\\:*?"<>|]+', "", key).strip()
        if cleaned:
            return cleaned
    return ROUTE_UNROUTED


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


def vault_po_reference_label(po_reference: str | None) -> str | None:
    """Sanitised PO number for API metadata (not a storage folder)."""
    ref = (po_reference or "").strip()
    if not ref:
        return None
    cleaned = re.sub(r'[/\\:*?"<>|]+', "", ref).strip()
    return cleaned or None


# Backwards-compatible alias for callers that used folder naming.
vault_po_folder = vault_po_reference_label


def _purchase_doc_key(
    po_reference: str | None,
    invoice_no: str | None,
    invoice_id: int,
) -> str:
    ref = (po_reference or "").strip()
    if ref:
        return vault_doc_number(ref, invoice_id)
    return vault_doc_number(invoice_no, invoice_id)


def vault_file_name(
    invoice_no: str | None,
    invoice_id: int,
    invoice_date: date | str | None,
    original_filename: str,
    *,
    purchase_document_type: str | None = None,
    po_reference: str | None = None,
) -> str:
    if purchase_document_type in ("po", "grn", "invoice"):
        doc_no = _purchase_doc_key(po_reference, invoice_no, invoice_id)
    else:
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
    prefix = ""
    if purchase_document_type == "po":
        prefix = "PO_"
    elif purchase_document_type == "grn":
        prefix = "GRN_"
    elif purchase_document_type == "invoice":
        prefix = "INV_"
    return f"{prefix}{doc_no}_{date_part}{suffix}"


def build_vault_blob_name(
    org_slug: str,
    *,
    org_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
) -> str:
    """Azure blob path: invoice/{org}/{book}/{vendor}/{year}/{month}/{file}."""
    return _build_storage_blob_name(
        VAULT_ROOT,
        org_slug,
        org_name=org_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
    )


def build_rejected_blob_name(
    org_slug: str,
    *,
    org_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
) -> str:
    """Azure blob path: rejected/{org}/{book}/{vendor}/{year}/{month}/{file}."""
    return _build_storage_blob_name(
        REJECTED_ROOT,
        org_slug,
        org_name=org_name,
        route_target=route_target,
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
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
) -> str:
    org = vault_org_folder(org_slug, org_name)
    book = vault_book_folder(route_target)
    vendor = vault_vendor_folder(vendor_name, storage_vendor_slug)
    year = vault_year(invoice_date)
    month = vault_month(invoice_date)
    file_name = vault_file_name(
        invoice_no,
        invoice_id,
        invoice_date,
        original_filename,
        purchase_document_type=purchase_document_type,
        po_reference=po_reference,
    )
    return f"{root}/{org}/{book}/{vendor}/{year}/{month}/{file_name}"


def build_virtual_path(
    org_slug: str,
    *,
    org_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
) -> str:
    return build_vault_blob_name(
        org_slug,
        org_name=org_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
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
    """Build org → book → vendor → year → month tree from vault entry dicts."""
    org_map: dict[str, dict[str, dict[str, dict[str, dict[str, int]]]]] = {}

    for entry in entries:
        org = entry["org"]
        book = entry["book"]
        vendor = entry["vendor"]
        year = entry["year"]
        month = entry["month"]
        org_map.setdefault(org, {}).setdefault(book, {}).setdefault(vendor, {}).setdefault(
            year, {}
        )
        bucket = org_map[org][book][vendor][year]
        bucket[month] = bucket.get(month, 0) + 1

    tree: list[dict[str, Any]] = []
    for org, books in org_map.items():
        org_count = sum(1 for e in entries if e["org"] == org)
        book_nodes: list[dict[str, Any]] = []
        for book, vendors in sorted(books.items()):
            book_count = sum(
                1 for e in entries if e["org"] == org and e["book"] == book
            )
            vendor_nodes: list[dict[str, Any]] = []
            for vendor, years in sorted(vendors.items()):
                vendor_count = sum(
                    1
                    for e in entries
                    if e["org"] == org and e["book"] == book and e["vendor"] == vendor
                )
                year_nodes: list[dict[str, Any]] = []
                for year, months in sorted(years.items(), key=lambda item: item[0], reverse=True):
                    year_count = sum(
                        1
                        for e in entries
                        if e["org"] == org
                        and e["book"] == book
                        and e["vendor"] == vendor
                        and e["year"] == year
                    )
                    month_nodes = []
                    for month, month_count in sorted(
                        months.items(), key=lambda item: _month_sort_index(item[0])
                    ):
                        month_nodes.append(
                            {
                                "id": f"{org}/{book}/{vendor}/{year}/{month}",
                                "label": month,
                                "kind": "month",
                                "count": month_count,
                                "children": [],
                            }
                        )
                    year_nodes.append(
                        {
                            "id": f"{org}/{book}/{vendor}/{year}",
                            "label": year,
                            "kind": "year",
                            "count": year_count,
                            "children": month_nodes,
                        }
                    )
                vendor_nodes.append(
                    {
                        "id": f"{org}/{book}/{vendor}",
                        "label": vendor,
                        "kind": "vendor",
                        "count": vendor_count,
                        "children": year_nodes,
                    }
                )
            book_nodes.append(
                {
                    "id": f"{org}/{book}",
                    "label": book,
                    "kind": "book",
                    "count": book_count,
                    "children": vendor_nodes,
                }
            )
        tree.append(
            {
                "id": org,
                "label": org,
                "kind": "org",
                "count": org_count,
                "children": book_nodes,
            }
        )
    return tree
