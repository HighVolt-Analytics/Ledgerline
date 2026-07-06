"""CSV export — documents bundle matrix for auditors."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import DossierLinkedDocumentsResponse
from app.services.audit.audit_export_service import linked_docs_by_dt_code
from app.services.classification.document_type_klass import is_trans_posting
from app.services.classification.document_type_playbook_service import (
    resolve_definition_for_invoice,
)
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.reports.reports_service import _load_invoices

_FIXED_COLUMNS = [
    "Class",
    "Posting",
    "DT type",
    "PO reference",
    "SO reference",
    "Invoice no.",
    "2 way match",
    "3 way match",
    "Universal match",
]


@dataclass(frozen=True)
class DocumentsBundleExportPayload:
    csv_text: str
    filename: str


def documents_bundle_filename(*, date_from: date | None) -> str:
    if date_from is not None:
        return f"documents_bundle_{date_from.year:04d}-{date_from.month:02d}.csv"
    return "documents_bundle.csv"


def _is_transactional_posting(defn: DocumentTypeDefinition | None) -> bool:
    if defn is None:
        return False
    return is_trans_posting(defn) and (defn.posting or "").strip() == "Yes"


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
) -> list[str]:
    klass = (definition.klass if definition else "").strip() or ""
    posting = (definition.posting if definition else "").strip() or ""
    two_way, three_way, universal = _match_flags(linked)
    by_dt = linked_docs_by_dt_code(
        invoice.id,
        linked,
        label_fn="bundle",
        invoice_dt_code_by_id=invoice_dt_code_by_id,
    )

    row: list[str] = [
        klass,
        posting,
        _dt_type_label(definition),
        (invoice.po_reference or "").strip(),
        (invoice.so_reference or "").strip(),
        (invoice.invoice_no or "").strip(),
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
) -> DocumentsBundleExportPayload:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    config = await load_posting_config_for_tenant(db, tenant_id)
    document_types = config.document_types
    dt_codes = _dt_codes_ordered(document_types)
    dt_headers = _dt_column_headers(document_types)

    invoices = await _load_invoices(
        db,
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
    )

    csv_rows: list[list[str]] = []
    for invoice in invoices:
        definition = resolve_definition_for_invoice(invoice, document_types)
        if not _is_transactional_posting(definition):
            continue

        linked = await build_dossier_linked_documents(
            db,
            invoice,
            definition=definition,
            document_types=document_types,
        )
        invoice_dt_codes = await _invoice_dt_code_by_id(db, linked)
        csv_rows.append(
            build_documents_bundle_row(
                invoice,
                definition=definition,
                linked=linked,
                dt_codes=dt_codes,
                invoice_dt_code_by_id=invoice_dt_codes,
            )
        )

    csv_text = documents_bundle_rows_to_csv(csv_rows, dt_column_headers=dt_headers)
    filename = documents_bundle_filename(date_from=date_from)
    return DocumentsBundleExportPayload(csv_text=csv_text, filename=filename)
