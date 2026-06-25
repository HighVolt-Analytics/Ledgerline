"""Shared types for document sample parsing."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.invoice import Invoice
from app.schemas.document_layout import DocumentLayoutResult
from app.services.invoice_data import InvoiceData


@dataclass(frozen=True)
class ParsedDocumentSample:
    filename: str
    invoice: Invoice
    parsed: InvoiceData
    confidence: str | None
    layout: DocumentLayoutResult | None = None
    layout_hint: str | None = None
