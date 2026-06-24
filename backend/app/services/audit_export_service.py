"""CSV export for organisation audit logs."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.dossier import DossierLinkedDocumentsResponse
from app.services.audit_change_summary import summarize_audit_change
from app.services.audit_detail_helpers import _latest_grn, truncate_audit_error
from app.services.public_app_url import build_public_app_path

_EXPORT_LIMIT = 10_000

_PURCHASE_SYNC_EVENTS = frozenset(
    {
        "purchase_po_document_synced",
        "purchase_grn_document_synced",
        "purchase_invoice_document_synced",
    }
)

_PURCHASE_VAULT_LINK_EVENTS = _PURCHASE_SYNC_EVENTS | frozenset(
    {"three_way_match_evaluated", "purchase_variance_approved"}
)


@dataclass(frozen=True)
class PurchaseVaultLinks:
    po_vault_url: str = ""
    grn_vault_url: str = ""
    invoice_vault_url: str = ""


_EMPTY_PURCHASE_VAULT_LINKS = PurchaseVaultLinks()

_CONFIG_NOISE_EVENTS = frozenset(
    {
        "rule_book_updated",
        "invoices_remapped",
        "vault_migrated",
    }
)

_INGEST_SKIP_EVENTS = frozenset({"email_skipped"})

_DEDUPE_LIFECYCLE_EVENTS = frozenset(
    {
        "purchase_po_document_synced",
        "purchase_grn_document_synced",
        "purchase_invoice_document_synced",
        "unmatched_team_vendor",
        "unmatched_expense_vendor",
        "blob_relocated",
        "parse_completed",
        "validation_passed",
        "mapping_applied",
        "three_way_match_evaluated",
    }
)

_CSV_COLUMNS = [
    "id",
    "created_at",
    "event",
    "invoice_id",
    "vault_url",
    "po_vault_url",
    "grn_vault_url",
    "invoice_vault_url",
    "linked_docs",
    "invoice_no",
    "route_target",
    "document_status",
    "evaluation_status",
    "correlation_id",
    "vendor_name",
    "po_number",
    "amount",
    "confidence_score",
    "ledger",
    "rule_matched",
    "hold_reason",
    "actor_name",
    "actor_email",
    "change_summary",
]


def dedupe_high_churn_audit_rows(rows: list[AuditLog]) -> list[AuditLog]:
    """Keep the newest row per (invoice_id, event) for remap-echo lifecycle events."""
    seen: set[tuple[int, str]] = set()
    kept: list[AuditLog] = []
    for row in rows:
        if row.invoice_id is not None and row.event in _DEDUPE_LIFECYCLE_EVENTS:
            key = (row.invoice_id, row.event)
            if key in seen:
                continue
            seen.add(key)
        kept.append(row)
    return kept


def _month_to_range(month: str) -> tuple[date, date]:
    year_s, month_s = month.split("-", 1)
    year, month_num = int(year_s), int(month_s)
    start = date(year, month_num, 1)
    if month_num == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month_num + 1, 1)
    last = end - timedelta(days=1)
    return start, last


def resolve_audit_export_range(
    *,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[date | None, date | None]:
    if month:
        start, end = _month_to_range(month)
        date_from = date_from or start
        date_to = date_to or end
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")
    return date_from, date_to


def format_audit_timestamp(value: datetime | None) -> str:
    """DD Mon YYYY, HH:MM UTC (e.g. 10 Jun 2026, 11:38 UTC)."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return f"{value.day} {value.strftime('%b %Y')}, {value.strftime('%H:%M')} UTC"


def _first_str(detail: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = detail.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def _first_scalar(detail: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in detail:
            continue
        raw = detail[key]
        if raw is None:
            continue
        if isinstance(raw, (int, float, Decimal)):
            return str(raw)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def purchase_vault_links_for_po(po: PurchaseOrder) -> PurchaseVaultLinks:
    """Vault URLs for PO, GRN, and supplier invoice legs of a purchase order."""
    grn = _latest_grn(po)
    grn_doc_id = grn.grn_invoice_id if grn is not None else None
    return PurchaseVaultLinks(
        po_vault_url=vault_view_path(po.po_document_id),
        grn_vault_url=vault_view_path(grn_doc_id),
        invoice_vault_url=vault_view_path(po.invoice_id),
    )


def _purchase_order_id_from_detail(detail: dict[str, Any]) -> int | None:
    raw = detail.get("purchase_order_id")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def resolve_purchase_vault_links(
    event: str,
    detail: dict[str, Any] | None,
    *,
    by_po_id: dict[int, PurchaseVaultLinks],
    by_po_number: dict[str, PurchaseVaultLinks],
) -> PurchaseVaultLinks:
    if event not in _PURCHASE_VAULT_LINK_EVENTS:
        return _EMPTY_PURCHASE_VAULT_LINKS
    d = detail if isinstance(detail, dict) else {}
    po_id = _purchase_order_id_from_detail(d)
    if po_id is not None:
        links = by_po_id.get(po_id)
        if links is not None:
            return links
    po_number = _first_str(d, "po_number")
    if po_number:
        return by_po_number.get(po_number, _EMPTY_PURCHASE_VAULT_LINKS)
    return _EMPTY_PURCHASE_VAULT_LINKS


async def fetch_purchase_vault_links_for_rows(
    db: AsyncSession,
    *,
    tenant_id: int,
    rows: list[AuditLog],
) -> tuple[dict[int, PurchaseVaultLinks], dict[str, PurchaseVaultLinks]]:
    po_ids: set[int] = set()
    po_numbers: set[str] = set()
    for row in rows:
        if row.event not in _PURCHASE_VAULT_LINK_EVENTS:
            continue
        detail = row.detail if isinstance(row.detail, dict) else {}
        po_id = _purchase_order_id_from_detail(detail)
        if po_id is not None:
            po_ids.add(po_id)
        po_number = _first_str(detail, "po_number")
        if po_number:
            po_numbers.add(po_number)

    if not po_ids and not po_numbers:
        return {}, {}

    filters = [PurchaseOrder.tenant_id == tenant_id]
    po_filters = []
    if po_ids:
        po_filters.append(PurchaseOrder.id.in_(po_ids))
    if po_numbers:
        po_filters.append(PurchaseOrder.po_number.in_(po_numbers))
    filters.append(or_(*po_filters))

    purchase_orders = (
        await db.execute(
            select(PurchaseOrder)
            .where(*filters)
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalars().all()

    by_po_id: dict[int, PurchaseVaultLinks] = {}
    by_po_number: dict[str, PurchaseVaultLinks] = {}
    for po in purchase_orders:
        links = purchase_vault_links_for_po(po)
        by_po_id[po.id] = links
        by_po_number[po.po_number] = links
    return by_po_id, by_po_number


def vault_view_path(invoice_id: int | None) -> str:
    """Clickable URL to open the document in Vault (Excel-friendly https://… link)."""
    if invoice_id is None:
        return ""
    return build_public_app_path(f"/vault?invoice={invoice_id}")


def _excel_csv_escape(value: str) -> str:
    return value.replace('"', '""')


def _absolute_vault_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return build_public_app_path(url)
    return build_public_app_path(f"/{url}")


def excel_hyperlink(url: str, label: str) -> str:
    """Excel CSV cell formula — one clickable link with a short label."""
    url = _absolute_vault_url(url)
    if not url:
        return ""
    text = (label or "Open").strip() or "Open"
    return (
        f'=HYPERLINK("{_excel_csv_escape(url)}","{_excel_csv_escape(text)}")'
    )


def excel_hyperlinks_joined(entries: list[tuple[str, str]]) -> str:
    """Excel CSV cell with multiple clickable links (one per line in the cell)."""
    parts: list[str] = []
    for url, label in entries:
        url = _absolute_vault_url(url)
        if not url:
            continue
        text = (label or "Open").strip() or "Open"
        parts.append(
            f'HYPERLINK("{_excel_csv_escape(url)}","{_excel_csv_escape(text)}")'
        )
    if not parts:
        return ""
    if len(parts) == 1:
        return f"={parts[0]}"
    return "=" + "&CHAR(10)&".join(parts)


def vault_csv_link(invoice_id: int | None, *, label: str = "View in Vault") -> str:
    return excel_hyperlink(vault_view_path(invoice_id), label)


def format_linked_docs_export(
    anchor_invoice_id: int,
    linked: DossierLinkedDocumentsResponse,
) -> str:
    """
    Excel-friendly linked dossier documents (bundle, invoice_no, manual).

    One clickable link per document; multiple links stack on separate lines in the cell.
    """
    link_entries: list[tuple[str, str]] = []
    seen: set[int] = {anchor_invoice_id}

    def add_entry(inv_id: int, dt_code: str, doc_ref: str | None) -> None:
        if inv_id in seen:
            return
        seen.add(inv_id)
        code = (dt_code or "").strip() or "?"
        ref = (doc_ref or "").strip()
        label = f"{code}:{ref}" if ref else code
        link_entries.append((vault_view_path(inv_id), label))

    for doc in linked.documents:
        if doc.is_anchor:
            continue
        if doc.manual_link is not None:
            ml = doc.manual_link
            add_entry(ml.invoice_id, ml.document_type_code, ml.document_ref)
            continue
        if doc.link_kind == "manual" and doc.invoice_id is not None:
            add_entry(doc.invoice_id, doc.document_type_code, doc.document_ref)
            continue
        if doc.link_kind == "invoice_no" and doc.invoice_id is not None:
            add_entry(doc.invoice_id, doc.document_type_code, doc.document_ref)
            continue
        if doc.present and doc.invoice_id is not None:
            add_entry(doc.invoice_id, doc.document_type_code, doc.document_ref)

    return excel_hyperlinks_joined(link_entries)


async def fetch_linked_docs_for_invoices(
    db: AsyncSession,
    *,
    tenant_id: int,
    invoice_map: dict[int, Invoice],
) -> dict[int, str]:
    """Build linked-docs export labels for each anchor invoice (same as dossier panel)."""
    if not invoice_map:
        return {}

    from app.services.document_type_playbook_service import resolve_definition_for_invoice
    from app.services.dossier_linked_documents_service import build_dossier_linked_documents
    from app.services.invoice_evaluation_service import load_posting_config_for_tenant

    config = await load_posting_config_for_tenant(db, tenant_id)
    document_types = config.document_types
    out: dict[int, str] = {}
    for inv_id, inv in invoice_map.items():
        definition = resolve_definition_for_invoice(inv, document_types)
        linked = await build_dossier_linked_documents(
            db,
            inv,
            definition=definition,
            document_types=document_types,
        )
        out[inv_id] = format_linked_docs_export(inv_id, linked)
    return out


def _invoice_amount_label(invoice: Invoice) -> str:
    if invoice.total is not None:
        return str(invoice.total)
    if invoice.subtotal is not None:
        return str(invoice.subtotal)
    return ""


def _rule_matched_label(detail: dict[str, Any]) -> str:
    rule_type = _first_str(detail, "rule_type")
    match_reason = _first_str(detail, "match_reason")
    if match_reason and rule_type:
        prefix = f"{rule_type}:"
        if match_reason.lower().startswith(prefix.lower()):
            return match_reason
        return f"{rule_type}: {match_reason}"
    if match_reason:
        return match_reason
    if rule_type:
        return rule_type
    return _first_str(detail, "rule_name", "rule_id")


def flatten_audit_detail(
    detail: dict[str, Any] | None,
    *,
    event: str = "",
    invoice: Invoice | None = None,
) -> dict[str, str]:
    """Extract auditor-facing columns from audit detail JSON."""
    d = detail if isinstance(detail, dict) else {}
    flat = {
        "invoice_no": _first_str(d, "invoice_no"),
        "route_target": _first_str(d, "route_target"),
        "document_status": _first_str(d, "document_status"),
        "evaluation_status": _first_str(d, "evaluation_status"),
        "vendor_name": _first_str(d, "vendor_name", "vendor", "merchant"),
        "po_number": _first_str(d, "po_number"),
        "amount": _first_scalar(d, "amount"),
        "confidence_score": _first_scalar(d, "confidence_score", "vendor_confidence"),
        "ledger": _first_str(
            d,
            "ledger",
            "account_name",
            "account_code",
            "expense_category",
        ),
        "rule_matched": _rule_matched_label(d),
        "hold_reason": "",
        "actor_name": _first_str(d, "actor_name"),
        "actor_email": _first_str(d, "actor_email"),
    }

    if event == "ingest_capture_matched":
        rule_name = _first_str(d, "rule_name")
        if rule_name:
            flat["rule_matched"] = f"Ingestion · {rule_name}"

    if event not in ("reconciliation_skipped", "email_moved"):
        raw_hold = _first_str(d, "hold_reason", "reason", "error")
        flat["hold_reason"] = (
            truncate_audit_error(raw_hold)
            if event == "pipeline_error"
            else raw_hold
        )

    if event == "parse_completed":
        source = _first_str(d, "source")
        confidence = _first_str(d, "confidence")
        if source and confidence:
            flat["confidence_score"] = confidence
            flat["rule_matched"] = f"parser: {source}"

    if invoice is not None:
        if not flat["invoice_no"]:
            doc_type = (invoice.purchase_document_type or "").strip().lower()
            po_ref = (invoice.po_reference or "").strip()
            if invoice.invoice_no:
                flat["invoice_no"] = invoice.invoice_no.strip()
            elif doc_type in ("po", "grn") and po_ref:
                flat["invoice_no"] = f"{doc_type.upper()}-{po_ref}"
        if not flat["route_target"]:
            flat["route_target"] = (invoice.route_target or "").strip()
        if not flat["document_status"]:
            flat["document_status"] = invoice.status.value if invoice.status else ""
        if not flat["evaluation_status"]:
            flat["evaluation_status"] = (invoice.evaluation_status or "").strip()
        if not flat["vendor_name"]:
            flat["vendor_name"] = (invoice.vendor or "").strip()
        if not flat["po_number"]:
            flat["po_number"] = (invoice.po_reference or "").strip()
        if not flat["amount"]:
            flat["amount"] = _invoice_amount_label(invoice)
        if not flat["confidence_score"] and invoice.vendor_confidence is not None:
            flat["confidence_score"] = str(invoice.vendor_confidence)
        if not flat["ledger"] and invoice.account_name:
            flat["ledger"] = invoice.account_name.strip()

    if event in _PURCHASE_SYNC_EVENTS and invoice is not None:
        if not flat["vendor_name"]:
            flat["vendor_name"] = (invoice.vendor or "").strip()
        if not flat["amount"]:
            flat["amount"] = _invoice_amount_label(invoice)

    return flat


async def fetch_audit_rows_for_export(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    document_only: bool = False,
    dedupe: bool = False,
) -> tuple[
    list[AuditLog],
    dict[int, Invoice],
    dict[int, PurchaseVaultLinks],
    dict[str, PurchaseVaultLinks],
    dict[int, str],
]:
    org_filter = or_(
        AuditLog.tenant_id == tenant_id,
        AuditLog.invoice_id.in_(select(Invoice.id).where(Invoice.tenant_id == tenant_id)),
    )
    stmt = (
        select(AuditLog)
        .where(org_filter)
        .order_by(AuditLog.created_at.desc())
        .limit(_EXPORT_LIMIT)
    )
    if date_from is not None:
        start_dt = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(AuditLog.created_at >= start_dt)
    if date_to is not None:
        end_dt = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        stmt = stmt.where(AuditLog.created_at <= end_dt)
    rows = list((await db.execute(stmt)).scalars().all())
    if document_only:
        rows = [
            row
            for row in rows
            if row.event not in _CONFIG_NOISE_EVENTS
            and (
                row.invoice_id is not None
                or row.event in _INGEST_SKIP_EVENTS
            )
        ]
    if dedupe:
        rows = dedupe_high_churn_audit_rows(rows)

    invoice_ids = {row.invoice_id for row in rows if row.invoice_id is not None}
    invoice_map: dict[int, Invoice] = {}
    if invoice_ids:
        invoices = (
            await db.execute(select(Invoice).where(Invoice.id.in_(invoice_ids)))
        ).scalars().all()
        invoice_map = {inv.id: inv for inv in invoices}

    by_po_id, by_po_number = await fetch_purchase_vault_links_for_rows(
        db,
        tenant_id=tenant_id,
        rows=rows,
    )
    linked_docs = await fetch_linked_docs_for_invoices(
        db,
        tenant_id=tenant_id,
        invoice_map=invoice_map,
    )
    return rows, invoice_map, by_po_id, by_po_number, linked_docs


def audit_rows_to_csv(
    rows: list[AuditLog],
    *,
    invoice_map: dict[int, Invoice] | None = None,
    purchase_vault_by_po_id: dict[int, PurchaseVaultLinks] | None = None,
    purchase_vault_by_po_number: dict[str, PurchaseVaultLinks] | None = None,
    linked_docs_by_invoice: dict[int, str] | None = None,
) -> str:
    invoices = invoice_map or {}
    by_po_id = purchase_vault_by_po_id or {}
    by_po_number = purchase_vault_by_po_number or {}
    linked_docs_map = linked_docs_by_invoice or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        invoice = invoices.get(row.invoice_id) if row.invoice_id is not None else None
        flat = flatten_audit_detail(detail, event=row.event, invoice=invoice)
        validation_json = invoice.validation_results if invoice is not None else None
        purchase_links = resolve_purchase_vault_links(
            row.event,
            detail,
            by_po_id=by_po_id,
            by_po_number=by_po_number,
        )
        linked_docs = ""
        if row.invoice_id is not None:
            linked_docs = linked_docs_map.get(row.invoice_id, "")
        writer.writerow(
            [
                row.id,
                format_audit_timestamp(row.created_at),
                row.event,
                row.invoice_id if row.invoice_id is not None else "",
                vault_csv_link(row.invoice_id),
                excel_hyperlink(purchase_links.po_vault_url, "Open PO"),
                excel_hyperlink(purchase_links.grn_vault_url, "Open GRN"),
                excel_hyperlink(purchase_links.invoice_vault_url, "Open invoice"),
                linked_docs,
                flat["invoice_no"],
                flat["route_target"],
                flat["document_status"],
                flat["evaluation_status"],
                row.correlation_id or "",
                flat["vendor_name"],
                flat["po_number"],
                flat["amount"],
                flat["confidence_score"],
                flat["ledger"],
                flat["rule_matched"],
                flat["hold_reason"],
                flat["actor_name"],
                flat["actor_email"],
                summarize_audit_change(
                    row.event,
                    detail,
                    validation_results_json=validation_json,
                ),
            ]
        )
    return buffer.getvalue()
