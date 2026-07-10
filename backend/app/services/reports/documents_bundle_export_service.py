"""CSV export — documents bundle matrix for auditors.

Matrix layout (one row per transactional posting anchor invoice):

Fixed columns
    Class, Posting, DT type, Invoice date, Counterparty, Total, Currency, Linkage,
    PO reference, SO reference, Invoice no. (vault hyperlink), Status,
    2/3/Universal match flags.

Dynamic DT columns (org-configured document types from rule book)
    One column per document type the organisation has defined in rule book
    (not the full shipped template catalogue), sorted alphabetically by DT code.
    Cell values:
        - Linked upload: Excel ``=HYPERLINK(url, label)`` (default) or ``label | url`` (plain)
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

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

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
    "Class",
    "Posting",
    "DT type",
    "Invoice date",
    "Counterparty",
    "Total",
    "Currency",
    "Linkage",
    "PO reference",
    "SO reference",
    "Invoice no.",
    "Status",
    "2 way match",
    "3 way match",
    "Universal match",
]


@dataclass(frozen=True)
class DocumentsBundleExportPayload:
    csv_text: str
    filename: str


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
        return f"documents_bundle_{date_from.year:04d}-{date_from.month:02d}.csv"
    return "documents_bundle.csv"


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
) -> list[str]:
    klass = (definition.klass if definition else "").strip() or ""
    posting = (definition.posting if definition else "").strip() or ""
    two_way, three_way, universal = _match_flags(linked)
    by_dt = bundle_dt_cells_by_code(
        invoice.id,
        linked,
        dt_codes,
        invoice_dt_code_by_id=invoice_dt_code_by_id,
        cell_format=cell_format,
    )

    row: list[str] = [
        klass,
        posting,
        _dt_type_label(definition),
        _invoice_date_label(invoice),
        (invoice.vendor or "").strip(),
        _total_label(invoice),
        (invoice.currency or "").strip(),
        (linked.linkage_kind or "").strip(),
        (invoice.po_reference or "").strip(),
        (invoice.so_reference or "").strip(),
        _invoice_no_cell(invoice, cell_format=cell_format),
        (invoice.status.value if invoice.status is not None else "").strip(),
        two_way,
        three_way,
        universal,
    ]
    row.extend(by_dt.get(code, "") for code in dt_codes)
    return row


def documents_bundle_rows_to_csv(
    rows: list[list[str]],
    *,
    dt_column_headers: list[str],
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([*_FIXED_COLUMNS, *dt_column_headers])
    writer.writerows(rows)
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

    csv_rows: list[list[str]] = []
    for ctx in contexts:
        csv_rows.append(
            build_documents_bundle_row(
                ctx.invoice,
                definition=ctx.definition,
                linked=ctx.linked,
                dt_codes=dt_codes,
                invoice_dt_code_by_id=ctx.invoice_dt_code_by_id,
                cell_format=cell_format,
            )
        )

    csv_text = documents_bundle_rows_to_csv(csv_rows, dt_column_headers=dt_headers)
    filename = documents_bundle_filename(date_from=date_from)
    return DocumentsBundleExportPayload(csv_text=csv_text, filename=filename)
