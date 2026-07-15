"""Excel export — documents bundle matrix for auditors.

Matrix layout (one row per transactional posting anchor invoice):

Fixed columns
    Timestamp, Uploaded by, Source, DT type, Invoice date,
    Counterparty, Total, Currency, Linkage, PO reference, SO reference,
    Invoice no. (vault hyperlink), Universal match.

Dynamic DT columns (org-configured document types from rule book)
    One column per document type the organisation has defined in rule book
    (not the full shipped template catalogue), sorted alphabetically by DT code.
    Cell values:
        - Linked upload: native Excel hyperlink (default) or ``label | url`` (plain)
        - Mandatory slot missing: ``Missing``
        - Advisory slot missing: ``Advisory``
        - Not applicable: empty

Row filter: active-workflow invoices (``PROCESSED``, ``EXCEPTION``, ``VALIDATING``,
``MAPPING``, ``JOURNALING``, ``RECONCILING``) where document type is Transactional with
posting Yes. Linked supporting docs match on PO/SO reference or invoice no as soon as
uploaded — no need to wait for anchor posting. Supporting-only documents appear in DT
columns, not as anchor rows.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, timezone
from typing import Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import DossierLinkedDocumentResponse, DossierLinkedDocumentsResponse
from app.services.audit.audit_export_service import (
    excel_hyperlink,
    linked_docs_by_dt_code,
    vault_view_path,
)
from app.services.classification.document_type_catalog import (
    org_document_types_for_bundle_export,
)
from app.services.classification.document_type_klass import (
    is_trans_posting,
    normalize_document_type_identity,
)
from app.services.classification.document_type_playbook_service import (
    resolve_definition_for_invoice,
)
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier.dossier_service import build_linkage_sibling_cache
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant

BundleCellFormat = Literal["excel", "plain"]

_BUNDLE_EXPORT_STATUSES = frozenset({
    InvoiceStatus.PROCESSED,
    InvoiceStatus.EXCEPTION,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
})

_FIXED_COLUMNS = [
    "Timestamp",
    "Uploaded by",
    "Source",
    "DT type",
    "Invoice date",
    "Counterparty",
    "Total",
    "Currency",
    "Linkage",
    "PO reference",
    "SO reference",
    "Invoice no.",
    "Universal match",
]

_MATCH_COLUMNS = frozenset({"Universal match"})

_TITLE_FILL = PatternFill("solid", fgColor="1F6E7A")
_TITLE_FONT = Font(color="FFFFFF", bold=True, size=14)
_HEADER_FILL = PatternFill("solid", fgColor="1F6E7A")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
_ZEBRA_FILL = PatternFill("solid", fgColor="F3F7F8")
_MISSING_FILL = PatternFill("solid", fgColor="F8D7DA")
_ADVISORY_FILL = PatternFill("solid", fgColor="FFF3CD")
_YES_FILL = PatternFill("solid", fgColor="D1E7DD")
_NO_FILL = PatternFill("solid", fgColor="E9ECEF")
_LINK_FONT = Font(color="0563C1", underline="single", size=10)
_BODY_FONT = Font(size=10)
_LEGEND_FONT = Font(size=9, color="334455")

_SINGLE_HYPERLINK_RE = re.compile(
    r'^=HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)$'
)

_TITLE_ROW = 1
_LEGEND_ROW = 2
_HEADER_ROW = 4
_FIRST_DATA_ROW = 5


@dataclass(frozen=True)
class DocumentsBundleExportPayload:
    xlsx_bytes: bytes
    filename: str
    data_rows: int


@dataclass(frozen=True)
class _AnchorExportContext:
    invoice: Invoice
    definition: DocumentTypeDefinition
    linked: DossierLinkedDocumentsResponse
    invoice_dt_code_by_id: dict[int, str]


def _effective_invoice_date():
    return func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))


async def _load_bundle_export_invoices(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Invoice]:
    """Load anchor candidates: active workflow statuses within the date window."""
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(_BUNDLE_EXPORT_STATUSES),
    )
    effective = _effective_invoice_date()
    if date_from is not None:
        stmt = stmt.where(effective >= date_from)
    if date_to is not None:
        stmt = stmt.where(effective <= date_to)
    stmt = stmt.order_by(effective.desc(), Invoice.id.desc())
    return list((await db.execute(stmt)).scalars().all())


def documents_bundle_filename(*, date_from: date | None) -> str:
    if date_from is not None:
        return f"documents_bundle_{date_from.year:04d}-{date_from.month:02d}.xlsx"
    return "documents_bundle.xlsx"


def _period_label(*, date_from: date | None, date_to: date | None) -> str:
    if date_from is not None and date_to is not None:
        if date_from == date_to:
            return date_from.isoformat()
        return f"{date_from.isoformat()} → {date_to.isoformat()}"
    if date_from is not None:
        return f"From {date_from.isoformat()}"
    if date_to is not None:
        return f"Through {date_to.isoformat()}"
    return "All dates"


def _is_transactional_posting(defn: DocumentTypeDefinition | None) -> bool:
    if defn is None:
        return False
    _, posting = normalize_document_type_identity(defn)
    return is_trans_posting(defn) and posting == "Yes"


def _dt_type_label(defn: DocumentTypeDefinition | None) -> str:
    if defn is None:
        return "Unclassified"
    short = (defn.short_title or "").strip()
    if short:
        return short
    return (defn.title or defn.code or "Unclassified").strip() or "Unclassified"


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _match_flags(linked: DossierLinkedDocumentsResponse) -> tuple[str, str, str]:
    status = (linked.match_summary.status if linked.match_summary else "").strip()
    two_way = _yes_no(status == "2-Way Match")
    three_way = _yes_no(status == "3-Way Match")

    universal = any(
        doc.link_kind == "invoice_no" and doc.present and doc.invoice_id is not None
        for doc in linked.documents
        if not doc.is_anchor
    )

    return two_way, three_way, _yes_no(universal)


def _invoice_date_label(invoice: Invoice) -> str:
    if invoice.invoice_date is not None:
        return invoice.invoice_date.isoformat()
    if invoice.created_at is not None:
        return invoice.created_at.date().isoformat()
    return ""


def _timestamp_label(invoice: Invoice) -> str:
    """When the document was received / uploaded (UTC)."""
    if invoice.created_at is None:
        return ""
    created = invoice.created_at
    if created.tzinfo is not None:
        created = created.astimezone(timezone.utc).replace(tzinfo=None)
    return created.strftime("%Y-%m-%d %H:%M:%S")


def _source_label(invoice: Invoice) -> str:
    src = (invoice.capture_source or "").strip().lower()
    if src == "email":
        return "Email"
    if src == "whatsapp":
        return "WhatsApp"
    if src == "viber":
        return "Viber"
    if src == "upload":
        return "Direct upload"
    sender = (invoice.email_sender or "").lower()
    if "onedrive" in sender or "sharepoint" in sender:
        return "OneDrive"
    if invoice.connected_mailbox_id or invoice.email_sender:
        return "Email"
    return "Direct upload"


def _uploaded_by_label(invoice: Invoice, *, upload_actor: str | None = None) -> str:
    """Manual uploader for direct upload; email/messaging sender otherwise."""
    name = (invoice.uploaded_by_name or "").strip()
    email = (invoice.uploaded_by_email or "").strip()
    if name or email:
        return name or email
    sender = (invoice.email_sender or "").strip()
    if sender:
        return sender
    return (upload_actor or "").strip()


def _total_label(invoice: Invoice) -> str:
    if invoice.total is not None:
        return str(invoice.total)
    if invoice.subtotal is not None:
        return str(invoice.subtotal)
    return ""


def _invoice_no_cell(invoice: Invoice, *, cell_format: BundleCellFormat) -> str:
    label = (invoice.invoice_no or "").strip()
    if not label:
        return ""
    url = vault_view_path(invoice.id)
    if cell_format == "plain":
        return f"{label} | {url}" if url else label
    return excel_hyperlink(url, label)


def _bundle_slots_by_dt_code(
    linked: DossierLinkedDocumentsResponse,
) -> dict[str, DossierLinkedDocumentResponse]:
    slots: dict[str, DossierLinkedDocumentResponse] = {}
    for doc in linked.documents:
        if doc.is_anchor:
            continue
        code = (doc.document_type_code or "").strip().upper()
        if not code:
            continue
        existing = slots.get(code)
        if existing is None:
            slots[code] = doc
            continue
        if doc.requirement == "mandatory" and existing.requirement != "mandatory":
            slots[code] = doc
    return slots


def _manual_link_cell(
    manual_link,
    *,
    cell_format: BundleCellFormat,
) -> str:
    ref = (manual_link.document_ref or "").strip() or f"DOC-{manual_link.invoice_id}"
    url = vault_view_path(manual_link.invoice_id)
    if cell_format == "plain":
        return f"{ref} | {url}" if url else ref
    return excel_hyperlink(url, ref)


def bundle_dt_cells_by_code(
    anchor_invoice_id: int,
    linked: DossierLinkedDocumentsResponse,
    dt_codes: list[str],
    *,
    invoice_dt_code_by_id: dict[int, str] | None = None,
    cell_format: BundleCellFormat = "excel",
) -> dict[str, str]:
    """DT column cells with hyperlinks/plain links plus Missing/Advisory slot markers."""
    linked_cells = linked_docs_by_dt_code(
        anchor_invoice_id,
        linked,
        label_fn="bundle",
        invoice_dt_code_by_id=invoice_dt_code_by_id,
        cell_format=cell_format,
    )
    slots_by_dt = _bundle_slots_by_dt_code(linked)

    out: dict[str, str] = {}
    for code in dt_codes:
        if linked_cells.get(code):
            out[code] = linked_cells[code]
            continue
        slot = slots_by_dt.get(code)
        if slot is None:
            out[code] = ""
        elif slot.manual_link is not None:
            out[code] = _manual_link_cell(slot.manual_link, cell_format=cell_format)
        elif slot.present:
            out[code] = linked_cells.get(code, "")
        elif slot.requirement == "mandatory":
            out[code] = "Missing"
        elif slot.requirement == "advisory":
            out[code] = "Advisory"
        else:
            out[code] = ""
    return out


async def _invoice_dt_code_by_id(
    db: AsyncSession,
    linked: DossierLinkedDocumentsResponse,
) -> dict[int, str]:
    invoice_ids = {
        doc.invoice_id
        for doc in linked.documents
        if doc.invoice_id is not None and not doc.is_anchor
    }
    for doc in linked.documents:
        if doc.manual_link is not None:
            invoice_ids.add(doc.manual_link.invoice_id)
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(Invoice.id, Invoice.document_type_code).where(
                Invoice.id.in_(invoice_ids)
            )
        )
    ).all()
    return {
        row.id: (row.document_type_code or "").strip().upper()
        for row in rows
        if (row.document_type_code or "").strip()
    }


def _sorted_tenant_document_types(
    document_types: list[DocumentTypeDefinition],
) -> list[DocumentTypeDefinition]:
    return sorted(
        document_types,
        key=lambda row: (row.code or "").upper(),
    )


def _dt_column_headers(document_types: list[DocumentTypeDefinition]) -> list[str]:
    headers: list[str] = []
    seen: set[str] = set()
    for row in _sorted_tenant_document_types(document_types):
        label = (row.short_title or row.title or row.code).strip() or row.code
        if label in seen:
            label = f"{label} ({row.code})"
        seen.add(label)
        headers.append(label)
    return headers


def _dt_codes_ordered(document_types: list[DocumentTypeDefinition]) -> list[str]:
    return [row.code.upper() for row in _sorted_tenant_document_types(document_types)]


def build_documents_bundle_row(
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None,
    linked: DossierLinkedDocumentsResponse,
    dt_codes: list[str],
    invoice_dt_code_by_id: dict[int, str] | None = None,
    cell_format: BundleCellFormat = "excel",
    upload_actor: str | None = None,
) -> list[str]:
    _, _, universal = _match_flags(linked)
    by_dt = bundle_dt_cells_by_code(
        invoice.id,
        linked,
        dt_codes,
        invoice_dt_code_by_id=invoice_dt_code_by_id,
        cell_format=cell_format,
    )

    row: list[str] = [
        _timestamp_label(invoice),
        _uploaded_by_label(invoice, upload_actor=upload_actor),
        _source_label(invoice),
        _dt_type_label(definition),
        _invoice_date_label(invoice),
        (invoice.vendor or "").strip(),
        _total_label(invoice),
        (invoice.currency or "").strip(),
        (linked.linkage_kind or "").strip(),
        (invoice.po_reference or "").strip(),
        (invoice.so_reference or "").strip(),
        _invoice_no_cell(invoice, cell_format=cell_format),
        universal,
    ]
    row.extend(by_dt.get(code, "") for code in dt_codes)
    return row


async def _upload_actors_by_invoice_id(
    db: AsyncSession,
    invoice_ids: list[int],
) -> dict[int, str]:
    """Map invoice id → uploader from invoice_uploaded audit (name preferred, else email)."""
    if not invoice_ids:
        return {}
    from app.models.audit import AuditLog

    rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event == "invoice_uploaded",
            )
            .order_by(AuditLog.created_at.asc())
        )
    ).scalars().all()

    actors: dict[int, str] = {}
    for log in rows:
        if log.invoice_id is None or log.invoice_id in actors:
            continue
        detail = log.detail if isinstance(log.detail, dict) else {}
        name = str(detail.get("actor_name") or "").strip()
        email = str(detail.get("actor_email") or "").strip()
        label = name or email
        if label:
            actors[log.invoice_id] = label
    return actors


def _unescape_excel_csv(value: str) -> str:
    return value.replace('""', '"')


def _parse_single_hyperlink_formula(value: str) -> tuple[str, str] | None:
    match = _SINGLE_HYPERLINK_RE.match((value or "").strip())
    if match is None:
        return None
    url = _unescape_excel_csv(match.group(1))
    label = _unescape_excel_csv(match.group(2))
    return url, label


def _autosize_columns(ws: Worksheet, *, max_width: int = 36) -> None:
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, min_row=_HEADER_ROW):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, min(len(str(cell.value)), 48))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 11), max_width)


def _write_title_and_period(
    ws: Worksheet,
    *,
    col_count: int,
    date_from: date | None,
    date_to: date | None,
) -> None:
    ws.merge_cells(start_row=_TITLE_ROW, start_column=1, end_row=_TITLE_ROW, end_column=max(col_count, 1))
    title_cell = ws.cell(row=_TITLE_ROW, column=1, value="Documents Bundle")
    title_cell.fill = _TITLE_FILL
    title_cell.font = _TITLE_FONT
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    for col in range(2, col_count + 1):
        cell = ws.cell(row=_TITLE_ROW, column=col)
        cell.fill = _TITLE_FILL
    ws.row_dimensions[_TITLE_ROW].height = 28

    period = _period_label(date_from=date_from, date_to=date_to)
    ws.cell(row=_LEGEND_ROW, column=1, value=f"Period: {period}").font = _LEGEND_FONT
    ws.row_dimensions[_LEGEND_ROW].height = 18

    # Spacer row keeps title/period visually separate from the table header.
    ws.row_dimensions[3].height = 8


def _apply_data_cell_style(
    cell,
    *,
    header: str,
    raw_value: str,
    zebra: bool,
    link_mode: BundleCellFormat,
) -> None:
    cell.font = _BODY_FONT
    cell.alignment = Alignment(vertical="center", wrap_text=True)

    value = raw_value
    if link_mode == "excel":
        parsed = _parse_single_hyperlink_formula(raw_value)
        if parsed is not None:
            url, label = parsed
            cell.value = label
            cell.hyperlink = url
            cell.font = _LINK_FONT
            value = label
        else:
            cell.value = raw_value
            if raw_value.startswith("=") and "HYPERLINK(" in raw_value:
                # Multi-link formula cell — keep formula; Excel renders clickable links.
                cell.font = _LINK_FONT
    else:
        cell.value = raw_value
        if " | " in raw_value and "/vault?" in raw_value:
            cell.font = _LINK_FONT

    fill = None
    if value == "Missing":
        fill = _MISSING_FILL
    elif value == "Advisory":
        fill = _ADVISORY_FILL
    elif header in _MATCH_COLUMNS:
        if value == "Yes":
            fill = _YES_FILL
        elif value == "No":
            fill = _NO_FILL
    elif zebra:
        fill = _ZEBRA_FILL

    if fill is not None:
        cell.fill = fill


def documents_bundle_rows_to_xlsx(
    rows: list[list[str]],
    *,
    dt_column_headers: list[str],
    date_from: date | None = None,
    date_to: date | None = None,
    cell_format: BundleCellFormat = "excel",
) -> bytes:
    """Build a styled workbook for the documents bundle matrix."""
    headers = [*_FIXED_COLUMNS, *dt_column_headers]
    wb = Workbook()
    ws = wb.active
    ws.title = "Documents Bundle"

    _write_title_and_period(
        ws,
        col_count=len(headers),
        date_from=date_from,
        date_to=date_to,
    )

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=_HEADER_ROW, column=col_idx, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[_HEADER_ROW].height = 24

    for row_offset, row in enumerate(rows):
        excel_row = _FIRST_DATA_ROW + row_offset
        zebra = row_offset % 2 == 1
        for col_idx, header in enumerate(headers, start=1):
            raw = row[col_idx - 1] if col_idx - 1 < len(row) else ""
            cell = ws.cell(row=excel_row, column=col_idx)
            _apply_data_cell_style(
                cell,
                header=header,
                raw_value=raw,
                zebra=zebra,
                link_mode=cell_format,
            )

    ws.freeze_panes = ws.cell(row=_FIRST_DATA_ROW, column=1)
    if rows:
        last_col = get_column_letter(len(headers))
        last_row = _FIRST_DATA_ROW + len(rows) - 1
        ws.auto_filter.ref = f"A{_HEADER_ROW}:{last_col}{last_row}"
    else:
        last_col = get_column_letter(max(len(headers), 1))
        ws.auto_filter.ref = f"A{_HEADER_ROW}:{last_col}{_HEADER_ROW}"

    _autosize_columns(ws)
    ws.sheet_view.showGridLines = False

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def build_documents_bundle_export(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    cell_format: BundleCellFormat = "excel",
) -> DocumentsBundleExportPayload:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    config = await load_posting_config_for_tenant(db, tenant_id)
    invoices = await _load_bundle_export_invoices(
        db,
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    catalogue = org_document_types_for_bundle_export(config.document_types)
    export_dt_types = _sorted_tenant_document_types(catalogue)
    dt_codes = _dt_codes_ordered(export_dt_types)
    dt_headers = _dt_column_headers(export_dt_types)

    anchors: list[Invoice] = []
    anchor_definitions: dict[int, DocumentTypeDefinition] = {}
    for invoice in invoices:
        definition = resolve_definition_for_invoice(invoice, catalogue)
        if not _is_transactional_posting(definition):
            continue
        assert definition is not None
        anchors.append(invoice)
        anchor_definitions[invoice.id] = definition

    linkage_cache = await build_linkage_sibling_cache(db, tenant_id=tenant_id, anchors=anchors)

    need_upload_actor = [
        inv.id for inv in anchors if not (inv.email_sender or "").strip()
    ]
    upload_actors = await _upload_actors_by_invoice_id(db, need_upload_actor)

    contexts: list[_AnchorExportContext] = []
    for invoice in anchors:
        definition = anchor_definitions[invoice.id]
        linked = await build_dossier_linked_documents(
            db,
            invoice,
            definition=definition,
            document_types=catalogue,
            linkage_cache=linkage_cache,
        )
        invoice_dt_codes = await _invoice_dt_code_by_id(db, linked)
        contexts.append(
            _AnchorExportContext(
                invoice=invoice,
                definition=definition,
                linked=linked,
                invoice_dt_code_by_id=invoice_dt_codes,
            )
        )

    data_rows: list[list[str]] = []
    for ctx in contexts:
        data_rows.append(
            build_documents_bundle_row(
                ctx.invoice,
                definition=ctx.definition,
                linked=ctx.linked,
                dt_codes=dt_codes,
                invoice_dt_code_by_id=ctx.invoice_dt_code_by_id,
                cell_format=cell_format,
                upload_actor=upload_actors.get(ctx.invoice.id),
            )
        )

    xlsx_bytes = documents_bundle_rows_to_xlsx(
        data_rows,
        dt_column_headers=dt_headers,
        date_from=date_from,
        date_to=date_to,
        cell_format=cell_format,
    )
    filename = documents_bundle_filename(date_from=date_from)
    return DocumentsBundleExportPayload(
        xlsx_bytes=xlsx_bytes,
        filename=filename,
        data_rows=len(data_rows),
    )
