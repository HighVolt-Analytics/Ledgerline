"""Vault folder paths — org → book → [document_type →] vendor → year → month → file."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services import blob_storage
from app.services.tenant_storage_paths import tenant_blob_name
from app.services.vendor_resolver import UNKNOWN_SLUG

ROUTE_PURCHASE = "Purchase Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"
ROUTE_UNROUTED = "Unrouted"

UNCLASSIFIED_DT_FOLDER = "Unclassified"

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

_STORAGE_ROOTS = frozenset({VAULT_ROOT, REJECTED_ROOT})


def slug_to_pascal(slug: str) -> str:
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Tenant"


def slug_to_title(slug: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in slug.split("-") if part)


def vault_tenant_folder(tenant_slug: str, tenant_name: str | None = None) -> str:
    if tenant_slug and tenant_slug.strip():
        return slug_to_pascal(tenant_slug)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", tenant_name or "Tenant").strip("_")
    return cleaned or "Tenant"


def is_vault_book_segment(segment: str) -> bool:
    """True when a path segment is a vault book (not a redundant org folder)."""
    key = (segment or "").strip()
    if not key:
        return False
    if key in _KNOWN_BOOKS:
        return True
    return " " in key


def strip_org_segment_from_blob_path(name: str) -> str | None:
    """Remove legacy org folder after invoice/ or rejected/ (tenant UUID already scopes data)."""
    norm = name.strip().lstrip("/").replace("\\", "/")
    if not norm:
        return None
    parts = norm.split("/")
    for root_name in _STORAGE_ROOTS:
        try:
            idx = parts.index(root_name)
        except ValueError:
            continue
        if idx + 2 >= len(parts):
            return None
        first_after = parts[idx + 1]
        second_after = parts[idx + 2]
        if is_vault_book_segment(first_after):
            return None
        if is_vault_book_segment(second_after) or second_after.startswith("DT-"):
            return "/".join(parts[: idx + 1] + parts[idx + 2 :])
    return None


def insert_org_segment_into_blob_path(name: str, org_folder: str) -> str | None:
    """Read fallback for blobs still stored with a legacy org folder segment."""
    org = (org_folder or "").strip()
    if not org:
        return None
    norm = name.strip().lstrip("/").replace("\\", "/")
    parts = norm.split("/")
    for root_name in _STORAGE_ROOTS:
        try:
            idx = parts.index(root_name)
        except ValueError:
            continue
        if idx + 1 >= len(parts):
            return None
        first_after = parts[idx + 1]
        if not is_vault_book_segment(first_after):
            return None
        return "/".join(parts[: idx + 1] + [org] + parts[idx + 1 :])
    return None


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


def vault_document_type_folder(
    document_type_code: str | None,
    *,
    short_title: str | None = None,
    title: str | None = None,
) -> str:
    """Display folder for vault-routed documents: ``DT-13 · Vendor statement``."""
    code = (document_type_code or "").strip().upper()
    label = (short_title or title or "").strip()
    if code and label:
        folder = f"{code} · {label}"
    elif code:
        folder = code
    elif label:
        folder = label
    else:
        folder = UNCLASSIFIED_DT_FOLDER
    # Azure blob paths must stay ASCII-safe; middle dots often corrupt to U+FFFD in storage.
    folder = folder.replace("\u00b7", " - ").replace("\ufffd", " - ")
    cleaned = re.sub(r'[/\\:*?"<>|]+', "", folder).strip()
    return cleaned or UNCLASSIFIED_DT_FOLDER


def vault_document_type_segment(
    route_target: str | None,
    document_type_code: str | None,
    *,
    short_title: str | None = None,
    title: str | None = None,
) -> str | None:
    """Extra path segment under the Vault book, or None for transactional books."""
    if vault_book_folder(route_target) != ROUTE_VAULT:
        return None
    return vault_document_type_folder(
        document_type_code,
        short_title=short_title,
        title=title,
    )


def _path_prefix(
    org: str,
    book: str,
    vendor: str,
    year: str,
    month: str,
    *,
    document_type: str | None = None,
) -> str:
    if document_type:
        return f"{org}/{book}/{document_type}/{vendor}/{year}/{month}"
    return f"{org}/{book}/{vendor}/{year}/{month}"


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
    # invoice_id keeps split dossier members unique when they share invoice_no / PO ref.
    return f"{prefix}{doc_no}_{date_part}_id{invoice_id}{suffix}"


def build_vault_blob_name(
    tenant_id: uuid.UUID,
    tenant_slug: str,
    *,
    tenant_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    """Azure blob path: invoice/{book}/[{dt}/]{vendor}/{year}/{month}/{file}."""
    dt_folder = document_type_folder
    if dt_folder is None:
        dt_folder = vault_document_type_segment(
            route_target,
            document_type_code,
            short_title=document_type_short_title,
            title=document_type_title,
        )
    return _build_storage_blob_name(
        tenant_id,
        VAULT_ROOT,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
        document_type_folder=dt_folder,
    )


def build_rejected_blob_name(
    tenant_id: uuid.UUID,
    tenant_slug: str,
    *,
    tenant_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    """Azure blob path: rejected/{book}/[{dt}/]{vendor}/{year}/{month}/{file}."""
    dt_folder = document_type_folder
    if dt_folder is None:
        dt_folder = vault_document_type_segment(
            route_target,
            document_type_code,
            short_title=document_type_short_title,
            title=document_type_title,
        )
    return _build_storage_blob_name(
        tenant_id,
        REJECTED_ROOT,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
        document_type_folder=dt_folder,
    )


def _build_storage_blob_name(
    tenant_id: uuid.UUID,
    root: str,
    tenant_slug: str,
    *,
    tenant_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
    document_type_folder: str | None = None,
) -> str:
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
    segments = [root, book]
    if document_type_folder:
        segments.append(document_type_folder)
    segments.extend([vendor, year, month, file_name])
    relative = "/".join(segments)
    return tenant_blob_name(tenant_id, relative)


def build_virtual_path(
    tenant_id: uuid.UUID,
    tenant_slug: str,
    *,
    tenant_name: str | None = None,
    route_target: str | None = None,
    vendor_name: str | None = None,
    storage_vendor_slug: str | None = None,
    invoice_id: int,
    invoice_no: str | None = None,
    invoice_date: date | str | None = None,
    original_filename: str,
    po_reference: str | None = None,
    purchase_document_type: str | None = None,
    document_type_code: str | None = None,
    document_type_short_title: str | None = None,
    document_type_title: str | None = None,
    document_type_folder: str | None = None,
) -> str:
    return build_vault_blob_name(
        tenant_id,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=route_target,
        vendor_name=vendor_name,
        storage_vendor_slug=storage_vendor_slug,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        original_filename=original_filename,
        po_reference=po_reference,
        purchase_document_type=purchase_document_type,
        document_type_code=document_type_code,
        document_type_short_title=document_type_short_title,
        document_type_title=document_type_title,
        document_type_folder=document_type_folder,
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


def _count_entries(entries: list[dict[str, Any]], **filters: str) -> int:
    return sum(1 for entry in entries if all(entry.get(k, "") == v for k, v in filters.items()))


def _build_month_nodes(
    entries: list[dict[str, Any]],
    *,
    org: str,
    book: str,
    document_type: str,
    vendor: str,
    year: str,
    months: dict[str, int],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for month, month_count in sorted(months.items(), key=lambda item: _month_sort_index(item[0])):
        nodes.append(
            {
                "id": _path_prefix(org, book, vendor, year, month, document_type=document_type or None),
                "label": month,
                "kind": "month",
                "count": month_count,
                "children": [],
            }
        )
    return nodes


def _build_year_nodes(
    entries: list[dict[str, Any]],
    *,
    org: str,
    book: str,
    document_type: str,
    vendor: str,
    years: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for year, months in sorted(years.items(), key=lambda item: item[0], reverse=True):
        year_count = _count_entries(
            entries,
            org=org,
            book=book,
            document_type=document_type,
            vendor=vendor,
            year=year,
        )
        year_id = (
            f"{org}/{book}/{document_type}/{vendor}/{year}"
            if document_type
            else f"{org}/{book}/{vendor}/{year}"
        )
        nodes.append(
            {
                "id": year_id,
                "label": year,
                "kind": "year",
                "count": year_count,
                "children": _build_month_nodes(
                    entries,
                    org=org,
                    book=book,
                    document_type=document_type,
                    vendor=vendor,
                    year=year,
                    months=months,
                ),
            }
        )
    return nodes


def _build_vendor_nodes(
    entries: list[dict[str, Any]],
    *,
    org: str,
    book: str,
    document_type: str,
    vendors: dict[str, dict[str, dict[str, int]]],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for vendor, years in sorted(vendors.items()):
        vendor_count = _count_entries(
            entries,
            org=org,
            book=book,
            document_type=document_type,
            vendor=vendor,
        )
        vendor_id = (
            f"{org}/{book}/{document_type}/{vendor}"
            if document_type
            else f"{org}/{book}/{vendor}"
        )
        nodes.append(
            {
                "id": vendor_id,
                "label": vendor,
                "kind": "vendor",
                "count": vendor_count,
                "children": _build_year_nodes(
                    entries,
                    org=org,
                    book=book,
                    document_type=document_type,
                    vendor=vendor,
                    years=years,
                ),
            }
        )
    return nodes


def build_vault_tree(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build org → book → [document_type →] vendor → year → month tree from vault entries."""
    # org → book → document_type → vendor → year → month
    org_map: dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, int]]]]]] = {}

    for entry in entries:
        org = entry["org"]
        book = entry["book"]
        document_type = (entry.get("document_type") or "").strip()
        vendor = entry["vendor"]
        year = entry["year"]
        month = entry["month"]
        org_map.setdefault(org, {}).setdefault(book, {}).setdefault(document_type, {}).setdefault(
            vendor, {}
        ).setdefault(year, {})
        bucket = org_map[org][book][document_type][vendor][year]
        bucket[month] = bucket.get(month, 0) + 1

    tree: list[dict[str, Any]] = []
    for org, books in org_map.items():
        org_count = _count_entries(entries, org=org)
        book_nodes: list[dict[str, Any]] = []
        for book, document_types in sorted(books.items()):
            book_count = _count_entries(entries, org=org, book=book)
            if set(document_types.keys()) == {""}:
                vendor_nodes = _build_vendor_nodes(
                    entries,
                    org=org,
                    book=book,
                    document_type="",
                    vendors=document_types[""],
                )
            else:
                vendor_nodes = []
                for document_type, vendors in sorted(document_types.items()):
                    if not document_type:
                        continue
                    dt_count = _count_entries(
                        entries,
                        org=org,
                        book=book,
                        document_type=document_type,
                    )
                    vendor_nodes.append(
                        {
                            "id": f"{org}/{book}/{document_type}",
                            "label": document_type,
                            "kind": "document_type",
                            "count": dt_count,
                            "children": _build_vendor_nodes(
                                entries,
                                org=org,
                                book=book,
                                document_type=document_type,
                                vendors=vendors,
                            ),
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
