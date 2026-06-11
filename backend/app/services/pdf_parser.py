"""Extract invoice fields from PDFs (local text tools, Azure DI fallback)."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.document_intelligence import (
    is_di_enabled,
    parse_with_document_intelligence,
)
from app.services.invoice_data import (
    InvoiceData,
    ParseConfidence,
    ParseResult,
    ParseSource,
)
from app.services.line_items_parser import ensure_line_items, parse_line_items_from_text
from app.services.vendor_name_utils import (
    extract_header_vendor,
    normalize_vendor_name,
    pick_best_vendor_name,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_REQUIRED_FOR_CONFIDENCE = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "subtotal",
    "gst",
    "total",
)

_DOC_TITLE_LINE = re.compile(
    r"^(?:purchase\s+order|goods\s+receipt(?:\s+note)?|tax\s+invoice|invoice|credit\s+note)\s*$",
    re.I,
)

_INVOICE_NO_STOPWORDS = frozenset(
    {
        "level",
        "date",
        "total",
        "amount",
        "invoice",
        "number",
        "no",
        "gst",
        "abn",
        "due",
        "bill",
        "to",
    }
)


def extract_pdf_text(path: Path) -> str:
    """Extract text with pdfplumber, then PyMuPDF if needed."""
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        logger.warning("pdfplumber_failed", error=str(exc))

    if not text.strip():
        import fitz

        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    return text


def _money(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _date(raw: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _normalize_abn(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 11:
        return digits[:11]
    return None


def _clean_vendor_candidate(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    for line in lines:
        if not _DOC_TITLE_LINE.match(line):
            return line
    return lines[-1] if lines else value.strip()


def _invoice_no_sane(value: str | None) -> bool:
    if not value or len(value) < 3:
        return False
    token = value.strip().lower()
    if token in _INVOICE_NO_STOPWORDS:
        return False
    if not re.search(r"\d", value) and len(value) < 6:
        return False
    return True


def parse_text_fields(text: str) -> dict[str, Any]:
    """Regex-based field extraction from plain text."""
    fields: dict[str, Any] = {}

    for pattern in (
        r"ABN[:\s]*(\d[\d\s]{10,14})",
        r"A\.?B\.?N\.?\s*(\d[\d\s]{10,14})",
        r"Tax\s*ID[:\s]*(\d[\d\s]{10,14})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["abn"] = _normalize_abn(m.group(1))
            break

    for pattern in (
        r"Invoice\s*(?:No\.?|Number|#)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"Inv(?:oice)?\s*#\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"Invoice\s*ID[:\s]*([A-Z0-9][A-Z0-9\-/_]{2,})",
    ):
        m = re.search(pattern, text, re.I)
        if m and _invoice_no_sane(m.group(1)):
            fields["invoice_no"] = m.group(1).strip()
            break

    vendor_patterns = [
        r"^([A-Za-z0-9][A-Za-z0-9\s&.,'\-]{2,50}?)\s+(?:TAX\s+INVOICE|INVOICE)\b",
        r"(?:From|Supplier|Vendor)[:\s]+([^\n]{3,80})",
        r"^([A-Za-z0-9][A-Za-z0-9\s&.,'\-]{2,60}(?:Pty\.?\s*Ltd\.?|Pty Ltd|Limited|Ltd\.?|Inc\.?))",
    ]
    for pattern in vendor_patterns:
        m = re.search(pattern, text, re.I | re.M)
        if m:
            candidate = _clean_vendor_candidate(m.group(1).strip())
            normalized = normalize_vendor_name(candidate)
            if normalized and "bill to" not in normalized.lower():
                fields["vendor"] = normalized
                break

    if not fields.get("vendor"):
        header_vendor = extract_header_vendor(text)
        if header_vendor:
            fields["vendor"] = header_vendor

    amount_patterns = [
        (r"Sub\s*Total(?:\s*AUD)?[:\s]*\$?\s*([\d,]+\.?\d*)", "subtotal"),
        (r"GST(?:\s*\d+%)?[:\s]*\$?\s*([\d,]+\.?\d*)", "gst"),
        (r"Invoice\s*Total[:\s]*\$?\s*([\d,]+\.?\d*)", "total"),
        (r"Amount\s*Due[:\s]*\$?\s*([\d,]+\.?\d*)", "total"),
        (r"(?<!Sub\s)TOTAL(?:\s*AUD)?(?:\s*Due)?[:\s]*\$?\s*([\d,]+\.?\d*)", "total"),
    ]
    for pattern, key in amount_patterns:
        if key in fields and fields[key] is not None:
            continue
        m = re.search(pattern, text, re.I)
        if m:
            fields[key] = _money(m.group(1))

    for pattern, key in (
        (r"Invoice\s*Date[:\s]*(\d{1,2}\s+\w+\s+\d{4})", "invoice_date"),
        (r"(?:Invoice\s*)?Date[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "invoice_date"),
        (r"(?:PO|Receipt)\s*Date[:\s]*(\d{1,2}\s+\w+\s+\d{4})", "invoice_date"),
        (r"Due\s*Date[:\s]*(\d{1,2}\s+\w+\s+\d{4})", "due_date"),
        (r"Due\s*Date[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "due_date"),
    ):
        m = re.search(pattern, text, re.I)
        if m and key not in fields:
            fields[key] = _date(m.group(1))

    for pattern in (
        r"Purchase\s*Order\s*(?:No\.?|Number)[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"PO\s*Reference[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"(?:^|\n)\s*P\.?O\.?\s*(?:No\.?|Number|#)?[:\s#]+([A-Z0-9][A-Z0-9\-/_]{2,})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["po_reference"] = m.group(1).strip()
            break

    for pattern in (
        r"Cost\s*Cent(?:re|er)[:\s]*([A-Z0-9][A-Z0-9\-/_]{1,30})",
        r"Project\s*(?:Code|No\.?)[:\s]*([A-Z0-9][A-Z0-9\-/_]{1,30})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["cost_centre"] = m.group(1).strip()
            break

    for pattern in (
        r"(?:Bill\s*From|Remit\s*To|Supplier\s*Address)[:\s]*\n?([^\n]+(?:\n[^\n]+){0,2})",
        r"(?:Address)[:\s]*([^\n]+\n[^\n]+\d{4})",
    ):
        m = re.search(pattern, text, re.I | re.M)
        if m:
            candidate = " ".join(line.strip() for line in m.group(1).splitlines() if line.strip())
            if len(candidate) >= 8:
                fields["billing_address"] = candidate[:500]
                break

    for pattern in (
        r"BSB[:\s]*(\d{3}[-\s]?\d{3})",
        r"\b(\d{3}-\d{3})\b",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["bank_bsb"] = m.group(1).strip()
            break

    for pattern in (
        r"(?:Account|Acc\.?)\s*(?:No\.?|Number)?[:\s]*(\d[\d\s]{5,12})",
        r"BSB[:\s]*\d{3}[-\s]?\d{3}[^\d]{0,20}(\d[\d\s]{5,12})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["bank_account"] = re.sub(r"\s+", "", m.group(1))
            break

    fields["line_items"] = parse_line_items_from_text(text)

    return fields


def _fields_to_invoice_data(fields: dict[str, Any], *, source: str) -> InvoiceData:
    meta = dict(fields)
    meta["parse_source"] = source
    return InvoiceData(
        vendor=fields.get("vendor"),
        abn=fields.get("abn"),
        billing_address=fields.get("billing_address"),
        bank_bsb=fields.get("bank_bsb"),
        bank_account=fields.get("bank_account"),
        invoice_no=fields.get("invoice_no"),
        invoice_date=fields.get("invoice_date"),
        due_date=fields.get("due_date"),
        currency=fields.get("currency") or "AUD",
        subtotal=fields.get("subtotal"),
        gst=fields.get("gst"),
        total=fields.get("total"),
        po_reference=fields.get("po_reference"),
        cost_centre=fields.get("cost_centre"),
        line_items=list(fields.get("line_items") or []),
        raw_fields=meta,
    )


def parse_local_text(text: str) -> InvoiceData:
    fields = parse_text_fields(text)
    return _fields_to_invoice_data(fields, source="local")


def count_present_fields(data: InvoiceData) -> int:
    return sum(
        1
        for name in _REQUIRED_FOR_CONFIDENCE
        if getattr(data, name) is not None
    )


def local_parse_confident(data: InvoiceData) -> bool:
    """True when local extraction has enough fields to skip Azure DI."""
    missing = [f for f in _REQUIRED_FOR_CONFIDENCE if getattr(data, f) is None]
    if missing:
        return False
    if not _invoice_no_sane(data.invoice_no):
        return False
    if data.subtotal and data.gst and data.total:
        expected = data.subtotal + data.gst
        if abs(data.total - expected) > Decimal("0.05"):
            return False
    return True


def should_use_document_intelligence(text: str, local: InvoiceData) -> bool:
    settings = get_settings()
    if not is_di_enabled():
        return False
    if len(text.strip()) < settings.parse_min_text_chars:
        return True
    if not local_parse_confident(local):
        return True
    return False


def _merge_prefer_complete(primary: InvoiceData, secondary: InvoiceData) -> InvoiceData:
    """Fill gaps in primary from secondary without overwriting set values."""
    line_items = primary.line_items or secondary.line_items
    merged = InvoiceData(
        vendor=pick_best_vendor_name(primary.vendor, secondary.vendor),
        abn=primary.abn or secondary.abn,
        billing_address=primary.billing_address or secondary.billing_address,
        bank_bsb=primary.bank_bsb or secondary.bank_bsb,
        bank_account=primary.bank_account or secondary.bank_account,
        invoice_no=primary.invoice_no or secondary.invoice_no,
        invoice_date=primary.invoice_date or secondary.invoice_date,
        due_date=primary.due_date or secondary.due_date,
        currency=primary.currency or secondary.currency or "AUD",
        subtotal=primary.subtotal or secondary.subtotal,
        gst=primary.gst or secondary.gst,
        total=primary.total or secondary.total,
        po_reference=primary.po_reference or secondary.po_reference,
        cost_centre=primary.cost_centre or secondary.cost_centre,
        line_items=list(line_items),
        raw_fields={
            "local": primary.raw_fields,
            "azure_di": secondary.raw_fields.get("azure_di", secondary.raw_fields),
        },
    )
    return merged


def _finalize_vendor(data: InvoiceData, text: str) -> InvoiceData:
    from dataclasses import replace

    vendor = pick_best_vendor_name(
        data.vendor,
        extract_header_vendor(text) if text.strip() else None,
    )
    if vendor == data.vendor:
        return data
    return replace(data, vendor=vendor)


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _parse_docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_invoice(file_path: str | Path) -> ParseResult:
    """
    Parse invoice attachments (PDF, image, DOCX): local first, Azure DI fallback.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        text = _parse_docx_text(path)
        local = parse_local_text(text)
        source: ParseSource = "local"
        confidence: ParseConfidence = "high" if local_parse_confident(local) else "low"
        final = local
        if should_use_document_intelligence(text, local):
            di_data = parse_with_document_intelligence(
                path, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            if di_data is not None:
                final = _merge_prefer_complete(di_data, local)
                source = "azure_di"
                confidence = "high" if local_parse_confident(final) else "low"
        ensure_line_items(final)
        final = _finalize_vendor(final, text)
        final.raw_fields["parse_source"] = source
        final.raw_fields["parse_confidence"] = confidence
        final.raw_fields["text_length"] = len(text.strip())
        return ParseResult(data=final, source=source, confidence=confidence, text_length=len(text.strip()))

    if suffix in {".jpg", ".jpeg", ".png"}:
        text = ""
        local = InvoiceData(currency="AUD")
        di_data = parse_with_document_intelligence(
            path, content_type=_content_type_for_path(path)
        )
        if di_data is None:
            final = local
            source = "local"
            confidence = "low"
        else:
            final = di_data
            source = "azure_di"
            confidence = "high" if local_parse_confident(final) else "low"
        ensure_line_items(final)
        final = _finalize_vendor(final, text)
        final.raw_fields["parse_source"] = source
        final.raw_fields["parse_confidence"] = confidence
        return ParseResult(data=final, source=source, confidence=confidence, text_length=0)

    text = extract_pdf_text(path)
    local = parse_local_text(text)

    source = "local"
    confidence: ParseConfidence = "low"
    final = local

    if should_use_document_intelligence(text, local):
        di_data = parse_with_document_intelligence(path)
        if di_data is not None:
            if local_parse_confident(local) and count_present_fields(local) >= count_present_fields(
                di_data
            ):
                final = local
                source = "local"
            else:
                final = _merge_prefer_complete(di_data, local)
                source = "azure_di"
            confidence = "high" if local_parse_confident(final) else "low"
        else:
            logger.info(
                "di_skipped_or_failed",
                path=str(path),
                text_length=len(text.strip()),
            )
            confidence = "high" if local_parse_confident(local) else "low"
    else:
        confidence = "high" if local_parse_confident(local) else "low"

    ensure_line_items(final)
    final = _finalize_vendor(final, text)
    final.raw_fields["parse_source"] = source
    final.raw_fields["parse_confidence"] = confidence
    final.raw_fields["text_length"] = len(text.strip())

    logger.info(
        "invoice_parsed",
        path=str(path),
        source=source,
        confidence=confidence,
        text_length=len(text.strip()),
        fields_present=count_present_fields(final),
    )

    return ParseResult(
        data=final,
        source=source,
        confidence=confidence,
        text_length=len(text.strip()),
    )
