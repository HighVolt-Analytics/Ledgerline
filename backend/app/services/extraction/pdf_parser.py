"""Extract invoice fields from PDFs (local text tools, Azure DI fallback)."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.shared.amount_sanity import plausible_money
from app.services.shared.flexible_date import parse_flexible_date
from app.services.extraction.document_intelligence import (
    is_di_enabled,
    parse_with_document_intelligence,
    read_pdf_page_texts_via_di,
)
from app.services.extraction.document_layout_service import analyze_layout_via_di
from app.services.extraction.layout_field_extractor import (
    extract_document_heading_from_layout,
    extract_key_value_fields,
    extract_line_items_from_tables,
    infer_doc_family_hint,
    layout_hint_suggests_invoice,
)
from app.services.extraction.document_text import cap_document_text
from app.services.invoice.invoice_data import (
    InvoiceData,
    ParseConfidence,
    ParseResult,
    ParseSource,
)
from app.services.extraction.line_items_parser import ensure_line_items, merge_line_item_lists, parse_line_items_from_text
from app.services.master_data.vendor_name_utils import (
    extract_header_vendor,
    extract_supplier_party_from_text,
    normalize_vendor_name,
    pick_best_vendor_name,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PHONE_LINE = re.compile(r"\b(?:phone|tel(?:ephone)?|mobile|fax|\+1|support@)\b", re.I)

_REQUIRED_FOR_CONFIDENCE = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "subtotal",
    "gst",
    "total",
)

from app.services.extraction.document_heading_utils import (
    extract_document_heading_signals,
    is_doc_title_line,
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


def _resolved_body_text(local_text: str, data: InvoiceData) -> str:
    """Prefer local PDF extract; fall back to Azure DI full-page content."""
    stripped = (local_text or "").strip()
    if stripped:
        return stripped
    return (data.document_text or "").strip()


def _attach_document_text(data: InvoiceData, text: str) -> InvoiceData:
    capped = cap_document_text(text)
    data.document_text = capped
    data.raw_fields["document_text"] = capped
    if not data.document_heading:
        signals = extract_document_heading_signals(capped)
        if signals.primary_label:
            data.document_heading = signals.primary_label
            data.raw_fields["document_heading"] = signals.primary_label
    return data


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
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return plausible_money(value)


def _date(raw: str) -> date | None:
    return parse_flexible_date(raw)


def _normalize_abn(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 11:
        return digits[:11]
    return None


def _clean_vendor_candidate(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    for line in lines:
        if not is_doc_title_line(line):
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

    signals = extract_document_heading_signals(text)
    if signals.primary_label:
        fields["document_heading"] = signals.primary_label

    is_po = signals.has_heading_po
    is_grn = signals.has_heading_grn
    is_invoice_doc = signals.has_heading_invoice and not is_po and not is_grn

    for pattern in (
        r"ABN[:\s]*(\d[\d\s]{10,14})",
        r"A\.?B\.?N\.?\s*(\d[\d\s]{10,14})",
        r"Tax\s*ID[:\s]*(\d[\d\s]{10,14})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            fields["abn"] = _normalize_abn(m.group(1))
            break

    if not fields.get("abn"):
        supplier_gstin = re.search(
            r"Supplier[\s\S]{0,200}?GSTIN[:\s]*([0-9]{2}[A-Z0-9]{13})",
            text,
            re.I,
        )
        if supplier_gstin:
            fields["gstin"] = supplier_gstin.group(1).upper()

    if not fields.get("abn") and not fields.get("gstin"):
        gstin = re.search(r"GSTIN[:\s]*([0-9]{2}[A-Z0-9]{13})", text, re.I)
        if gstin:
            fields["gstin"] = gstin.group(1).upper()

    if is_invoice_doc or not (is_po or is_grn):
        for pattern in (
            r"Invoice\s*(?:No\.?|Number|#)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
            r"Inv(?:oice)?\s*#\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
            r"Invoice\s*ID[:\s]*([A-Z0-9][A-Z0-9\-/_]{2,})",
            r"(?:^|[\s|])No:\s*([A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9\-/_]*)",
        ):
            m = re.search(pattern, text, re.I)
            if m and _invoice_no_sane(m.group(1)):
                fields["invoice_no"] = m.group(1).strip()
                break

    if is_grn and not fields.get("invoice_no"):
        m = re.search(
            r"(?:GRN|Goods\s+Receipt)\s*(?:No\.?|Number|#)?[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
            text,
            re.I,
        )
        if m and _invoice_no_sane(m.group(1)):
            fields["grn_reference"] = m.group(1).strip()

    vendor: str | None = None
    if is_po or is_grn:
        vendor = extract_supplier_party_from_text(text)
    if not vendor and not is_grn:
        vendor_patterns = [
            r"^([A-Za-z0-9][A-Za-z0-9\s&.,'\-]{2,50}?)\s+(?:TAX\s+INVOICE|INVOICE)\b",
            r"Bill\s+From[:\s]+([A-Za-z][^\n]{3,80})",
            r"^([A-Za-z0-9][A-Za-z0-9\s&.,'\-]{2,60}(?:Pty\.?\s*Ltd\.?|Pty Ltd|Limited|Ltd\.?|Inc\.?|Pvt\s+Ltd\.?))",
        ]
        for pattern in vendor_patterns:
            m = re.search(pattern, text, re.I | re.M)
            if m:
                candidate = _clean_vendor_candidate(m.group(1).strip())
                normalized = normalize_vendor_name(candidate)
                if normalized and "bill to" not in normalized.lower():
                    vendor = normalized
                    break
    if not vendor and not is_grn:
        vendor = extract_header_vendor(text)
    if vendor:
        fields["vendor"] = vendor

    from app.services.extraction.money_scalar_resolver import extract_money_scalars_from_text

    for key, amount in extract_money_scalars_from_text(text).items():
        if key not in fields or fields.get(key) is None:
            fields[key] = amount

    from app.services.extraction.gst_rate import parse_gst_rate_percent

    for pattern in (
        r"GST\s*\((\d+(?:\.\d+)?)\s*%\)",
        r"(?:GST|VAT|Tax)\s*(?:@|at)?\s*(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s*(?:GST|VAT|Tax)",
        r"(?:rate|tax)\s*(?:of|@)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:GST|VAT|Tax)?",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            parsed_rate = parse_gst_rate_percent(m.group(1))
            if parsed_rate is not None:
                fields["gst_rate"] = parsed_rate
                break

    if fields.get("gst_rate") is None:
        subtotal = fields.get("subtotal")
        gst = fields.get("gst")
        if subtotal and gst is not None and subtotal > 0:
            fields["gst_rate"] = ((gst / subtotal) * Decimal("100")).quantize(Decimal("0.01"))

    _date_value_pattern = (
        r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}"
        r"|\d{1,2}\s+\w+\s+\d{4}"
        r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
    )
    for pattern, key in (
        (rf"Date\s+of\s+[Ii]ssue[:\s]*{_date_value_pattern}", "invoice_date"),
        (rf"Issue\s*Date[:\s]*{_date_value_pattern}", "invoice_date"),
        (rf"Invoice\s*Date[:\s]*{_date_value_pattern}", "invoice_date"),
        (rf"(?:Invoice\s*)?Date[:\s]*(\d{{1,2}}[/\-]\d{{1,2}}[/\-]\d{{2,4}})", "invoice_date"),
        (r"(?:PO|Receipt|GRN)\s*Date[:\s]*(\d{1,2}\s+\w+\s+\d{4})", "invoice_date"),
    ):
        m = re.search(pattern, text, re.I)
        if m and key not in fields:
            fields[key] = _date(m.group(1))

    for pattern, key in (
        (rf"Date\s+[Dd]ue[:\s]*{_date_value_pattern}", "due_date"),
        (rf"Due\s*Date[:\s]*{_date_value_pattern}", "due_date"),
        (rf"Payment\s+Due(?:\s+Date)?[:\s]*{_date_value_pattern}", "due_date"),
    ):
        m = re.search(pattern, text, re.I)
        if m and key not in fields:
            fields[key] = _date(m.group(1))

    for pattern in (
        r"Purchase\s*Order\s+(?:No\.?|Number)\s*[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"Purchase\s*Order\s*(?:No\.?|Number)[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"PO\s*Reference[:\s#]*([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"(?:^|\n)\s*P\.?O\.?\s*(?:No\.?|Number|#)?[:\s#]+([A-Z0-9][A-Z0-9\-/_]{2,})",
        r"\bNo\.?\s*[:\s#]+(PO[-\s][A-Z0-9][A-Z0-9\-/_]{2,})",
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
        r"(?:Address)[:\s]*([^\n]+\n[^\n]+\d{4,6}\b)",
    ):
        m = re.search(pattern, text, re.I | re.M)
        if m:
            candidate = " ".join(line.strip() for line in m.group(1).splitlines() if line.strip())
            if len(candidate) >= 8:
                fields["billing_address"] = candidate[:500]
                break

    from app.services.extraction.party_field_service import sanitize_address
    from app.services.master_data.vendor_name_utils import (
        extract_buyer_address_from_text,
        extract_buyer_party_from_text,
        extract_seller_address_from_text,
    )

    buyer_addr = extract_buyer_address_from_text(text)
    if buyer_addr:
        fields["billing_address"] = sanitize_address(buyer_addr)
    elif fields.get("billing_address"):
        fields["billing_address"] = sanitize_address(fields["billing_address"])

    seller_addr = extract_seller_address_from_text(text)
    if seller_addr:
        fields.setdefault("seller_address", sanitize_address(seller_addr))
    buyer_name = extract_buyer_party_from_text(text)
    if buyer_name:
        fields.setdefault("buyer_name", buyer_name)

    for pattern in (
        r"(?:BSB|Bank\s*State\s*Branch)[:\s]*(\d{3}[-\s]?\d{3})",
    ):
        for line in text.splitlines():
            if _PHONE_LINE.search(line):
                continue
            m = re.search(pattern, line, re.I)
            if m:
                fields["bank_bsb"] = m.group(1).strip()
                break
        if fields.get("bank_bsb"):
            break

    for line in text.splitlines():
        if _PHONE_LINE.search(line):
            continue
        for pattern in (
            r"(?:Account|Acc\.?|A/C|IBAN)\s*(?:No\.?|Number)?[:\s]*(\d[\d\s]{5,12})",
            r"BSB[:\s]*\d{3}[-\s]?\d{3}[^\d]{0,20}(\d[\d\s]{5,12})",
        ):
            m = re.search(pattern, line, re.I)
            if m:
                fields["bank_account"] = re.sub(r"\s+", "", m.group(1))
                break
        if fields.get("bank_account"):
            break

    fields["line_items"] = parse_line_items_from_text(text)

    return fields


def post_process_parsed_data(
    data: InvoiceData,
    text: str,
    *,
    dt_definition: object | None = None,
) -> InvoiceData:
    """Heading-aware cleanup after local/DI merge."""
    from dataclasses import replace

    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.extraction.field_grounding_service import value_grounded_in_ocr

    body = (text or data.document_text or "").strip()
    if not body:
        return data

    signals = extract_document_heading_signals(body)
    if not data.document_heading and signals.primary_label:
        if value_grounded_in_ocr(signals.primary_label, body):
            data = replace(data, document_heading=signals.primary_label)

    vendor = data.vendor
    if signals.has_heading_grn:
        candidate = pick_best_vendor_name(
            extract_supplier_party_from_text(body),
            data.vendor,
        )
        if candidate and value_grounded_in_ocr(candidate, body):
            vendor = candidate
    elif not vendor:
        candidate = pick_best_vendor_name(
            extract_supplier_party_from_text(body) if signals.has_heading_po else None,
            data.vendor,
            extract_header_vendor(body),
        )
        if candidate and value_grounded_in_ocr(candidate, body):
            vendor = candidate

    invoice_no = data.invoice_no
    invoice_date = data.invoice_date
    if signals.has_heading_po or signals.has_heading_grn:
        invoice_no = None
    elif invoice_no:
        from app.services.extraction.invoice_no_sanitizer import (
            split_invoice_no_and_date,
        )

        clean_no, bleed_date = split_invoice_no_and_date(str(invoice_no))
        invoice_no = clean_no
        if bleed_date is not None and invoice_date is None:
            invoice_date = bleed_date

    if invoice_no and not _invoice_no_sane(invoice_no):
        invoice_no = None

    due_date = data.due_date
    if signals.has_heading_po or signals.has_heading_grn:
        due_date = None

    po_reference = data.po_reference
    dt_def = dt_definition if isinstance(dt_definition, DocumentTypeDefinition) else None
    configured: set[str] = set()
    if dt_def is not None:
        from app.services.extraction.extraction_field_values import effective_extraction_field_keys_for_dt

        configured = set(effective_extraction_field_keys_for_dt([dt_def], dt_def.code))

    if not po_reference and "po_reference" in configured:
        from app.services.purchase.po_reference import extract_po_reference_from_text

        candidate = extract_po_reference_from_text(body)
        if candidate and value_grounded_in_ocr(candidate, body):
            po_reference = candidate

    local_fields = parse_text_fields(body)
    raw_fields = dict(data.raw_fields or {})
    if local_fields.get("gstin") and not raw_fields.get("gstin"):
        gstin = str(local_fields["gstin"])
        if value_grounded_in_ocr(gstin, body):
            raw_fields["gstin"] = gstin
    if local_fields.get("grn_reference"):
        grn_ref = str(local_fields["grn_reference"])
        if value_grounded_in_ocr(grn_ref, body):
            raw_fields["grn_reference"] = grn_ref

    if not invoice_no and local_fields.get("invoice_no") and "invoice_no" in configured:
        candidate = local_fields["invoice_no"]
        if value_grounded_in_ocr(candidate, body):
            invoice_no = candidate
    if not po_reference and local_fields.get("po_reference") and "po_reference" in configured:
        candidate = local_fields["po_reference"]
        if value_grounded_in_ocr(candidate, body):
            po_reference = candidate

    if dt_def is not None:
        absent = {str(f).strip().lower() for f in (dt_def.absent_fields or []) if str(f).strip()}
        if "invoice_no" in absent:
            invoice_no = None
        if "due_date" in absent:
            due_date = None

    return replace(
        data,
        vendor=vendor,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        due_date=due_date,
        po_reference=po_reference or data.po_reference,
        raw_fields=raw_fields,
    )


def _fields_to_invoice_data(fields: dict[str, Any], *, source: str) -> InvoiceData:
    meta = dict(fields)
    meta["parse_source"] = source
    party_keys = (
        "seller_name",
        "seller_address",
        "buyer_name",
        "buyer_address",
        "billing_address",
    )
    extracted = {
        key: str(fields[key]).strip()
        for key in party_keys
        if fields.get(key) and str(fields[key]).strip()
    }
    return InvoiceData(
        vendor=fields.get("vendor"),
        abn=fields.get("abn"),
        billing_address=fields.get("billing_address"),
        bank_bsb=fields.get("bank_bsb"),
        bank_account=fields.get("bank_account"),
        invoice_no=fields.get("invoice_no"),
        invoice_date=fields.get("invoice_date"),
        due_date=fields.get("due_date"),
        currency=(fields.get("currency") or "").strip().upper() if fields.get("currency") else "",
        subtotal=fields.get("subtotal"),
        gst=fields.get("gst"),
        gst_rate=fields.get("gst_rate"),
        total=fields.get("total"),
        po_reference=fields.get("po_reference"),
        cost_centre=fields.get("cost_centre"),
        line_items=list(fields.get("line_items") or []),
        document_heading=fields.get("document_heading"),
        extracted_fields=extracted,
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


def sample_parse_confident(data: InvoiceData, layout_hint: str | None) -> bool:
    """Document-type-aware confidence for rule-book sample uploads."""
    hint = (layout_hint or data.raw_fields.get("layout_hint") or "").strip().lower()
    if hint in {"", "invoice", "credit_note"}:
        return local_parse_confident(data)
    if hint in {"po", "grn", "contract", "quote", "claim"}:
        heading = (data.document_heading or "").strip()
        if not heading:
            return False
        domain_count = sum(
            1
            for value in (
                data.vendor,
                data.po_reference,
                data.invoice_no,
                data.total,
                data.abn,
            )
            if value
        )
        return domain_count >= 2
    return local_parse_confident(data)


def _apply_layout_fields(
    data: InvoiceData,
    *,
    layout,
    body_text: str,
) -> InvoiceData:
    kv = extract_key_value_fields(layout, body_text)
    heading = extract_document_heading_from_layout(layout)
    if heading and not data.document_heading:
        data.document_heading = heading

    if kv.get("vendor") and not data.vendor:
        data.vendor = normalize_vendor_name(kv["vendor"]) or kv["vendor"]
    if kv.get("abn") and not data.abn:
        data.abn = _normalize_abn(kv["abn"])
    if kv.get("invoice_no") and not data.invoice_no:
        data.invoice_no = kv["invoice_no"].strip()
    if kv.get("po_reference") and not data.po_reference:
        data.po_reference = kv["po_reference"].strip()
    if kv.get("invoice_date") and not data.invoice_date:
        data.invoice_date = _date(kv["invoice_date"])
    if kv.get("due_date") and not data.due_date:
        data.due_date = _date(kv["due_date"])
    for money_key in ("subtotal", "gst", "total"):
        if kv.get(money_key) and getattr(data, money_key) is None:
            setattr(data, money_key, _money(kv[money_key]))

    table_items = extract_line_items_from_tables(layout)
    if table_items:
        data.line_items = merge_line_item_lists(data.line_items, table_items)

    if layout is not None:
        data.raw_fields["azure_layout"] = layout.raw
    if kv:
        data.raw_fields["layout_kv"] = kv
    return data


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
        currency=primary.currency or secondary.currency or "SGD",
        subtotal=primary.subtotal or secondary.subtotal,
        gst=primary.gst or secondary.gst,
        total=primary.total or secondary.total,
        po_reference=primary.po_reference or secondary.po_reference,
        cost_centre=primary.cost_centre or secondary.cost_centre,
        line_items=list(line_items),
        document_text=primary.document_text or secondary.document_text,
        document_heading=primary.document_heading or secondary.document_heading,
        raw_fields={
            "local": primary.raw_fields,
            "azure_di": secondary.raw_fields.get("azure_di", secondary.raw_fields),
        },
    )
    return merged


def _finalize_vendor(data: InvoiceData, text: str) -> InvoiceData:
    from dataclasses import replace

    signals = extract_document_heading_signals(text) if text.strip() else None
    supplier = (
        extract_supplier_party_from_text(text)
        if signals and (signals.has_heading_po or signals.has_heading_grn)
        else None
    )
    vendor = pick_best_vendor_name(
        supplier,
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
        body_text = _resolved_body_text(text, final)
        final = _attach_document_text(final, body_text)
        final = post_process_parsed_data(final, body_text)
        final.raw_fields["parse_source"] = source
        final.raw_fields["parse_confidence"] = confidence
        final.raw_fields["text_length"] = len(body_text)
        return ParseResult(data=final, source=source, confidence=confidence, text_length=len(body_text))

    if suffix in {".jpg", ".jpeg", ".png"}:
        text = ""
        local = InvoiceData(currency="SGD")
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
        body_text = _resolved_body_text(text, final)
        final = _attach_document_text(final, body_text)
        final = post_process_parsed_data(final, body_text)
        final.raw_fields["parse_source"] = source
        final.raw_fields["parse_confidence"] = confidence
        final.raw_fields["text_length"] = len(body_text)
        return ParseResult(data=final, source=source, confidence=confidence, text_length=len(body_text))

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
    body_text = _resolved_body_text(text, final)
    final = _attach_document_text(final, body_text)
    final = post_process_parsed_data(final, body_text)
    final.raw_fields["parse_source"] = source
    final.raw_fields["parse_confidence"] = confidence
    final.raw_fields["text_length"] = len(body_text)

    logger.info(
        "invoice_parsed",
        path=str(path),
        source=source,
        confidence=confidence,
        text_length=len(body_text),
        fields_present=count_present_fields(final),
    )

    return ParseResult(
        data=final,
        source=source,
        confidence=confidence,
        text_length=len(body_text),
    )


def _build_parse_result(
    path: Path,
    text: str,
    final: InvoiceData,
    *,
    source: ParseSource,
    confidence: ParseConfidence,
    layout_hint: str | None = None,
    layout=None,
) -> ParseResult:
    ensure_line_items(final)
    final = _finalize_vendor(final, text)
    body_text = _resolved_body_text(text, final)
    final = _attach_document_text(final, body_text)
    final = post_process_parsed_data(final, body_text)
    final.raw_fields["parse_source"] = source
    final.raw_fields["parse_confidence"] = confidence
    final.raw_fields["text_length"] = len(body_text)
    if layout_hint:
        final.raw_fields["layout_hint"] = layout_hint
    return ParseResult(
        data=final,
        source=source,
        confidence=confidence,
        text_length=len(body_text),
        layout_hint=layout_hint,
        layout=layout,
    )


def _richest_sample_body_text(*parts: str) -> str:
    """Pick the longest non-empty text chunk (usually the most complete OCR extract)."""
    candidates = [part.strip() for part in parts if part and part.strip()]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _read_body_text_via_di(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".jpg", ".jpeg", ".png"}:
        return ""
    pages = read_pdf_page_texts_via_di(path)
    if not pages:
        return ""
    return "\n".join(text for _, text in pages if text).strip()


def parse_invoice_for_sample(file_path: str | Path) -> ParseResult:
    """
    Rule-book sample uploads: layout OCR + targeted invoice DI when appropriate.

    Runs prebuilt-layout for structure, prebuilt-read for full text, and
    prebuilt-invoice only when the document looks invoice-like. Falls back to
    local extraction when Azure DI is unavailable.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    local_extracted = ""
    if suffix == ".docx":
        local_extracted = _parse_docx_text(path)
    elif suffix not in {".jpg", ".jpeg", ".png"}:
        local_extracted = extract_pdf_text(path)

    layout = None
    di_data: InvoiceData | None = None
    read_text = ""
    used_di = False
    layout_drove_fields = False

    if is_di_enabled():
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if suffix == ".docx"
            else _content_type_for_path(path)
        )
        layout = analyze_layout_via_di(path, content_type=content_type)
        if layout is not None:
            used_di = True
            if layout.content:
                read_text = layout.content
        if not read_text:
            read_text = _read_body_text_via_di(path) or ""
            if read_text:
                used_di = True

        preliminary_hint = infer_doc_family_hint(
            layout,
            extract_document_heading_from_layout(layout),
            read_text or local_extracted,
        )
        if layout_hint_suggests_invoice(preliminary_hint):
            di_data = parse_with_document_intelligence(path, content_type=content_type)
            if di_data is not None:
                used_di = True

    di_body = (di_data.document_text or "") if di_data is not None else ""
    layout_body = (layout.content or "") if layout is not None else ""
    body_text = _richest_sample_body_text(local_extracted, read_text, layout_body, di_body)
    local = parse_local_text(body_text) if body_text.strip() else InvoiceData(currency="SGD")

    if layout is not None:
        before_count = count_present_fields(local)
        local = _apply_layout_fields(local, layout=layout, body_text=body_text)
        if count_present_fields(local) > before_count:
            layout_drove_fields = True

    if di_data is not None:
        final = _merge_prefer_complete(di_data, local)
    else:
        final = local

    layout_hint = infer_doc_family_hint(
        layout,
        final.document_heading or extract_document_heading_from_layout(layout),
        body_text,
    )
    if layout_hint:
        final.raw_fields["layout_hint"] = layout_hint

    if layout_drove_fields:
        source: ParseSource = "azure_layout"
    elif used_di:
        source = "azure_di"
    else:
        source = "local"
    confidence: ParseConfidence = (
        "high" if sample_parse_confident(final, layout_hint) else "low"
    )
    return _build_parse_result(
        path,
        body_text,
        final,
        source=source,
        confidence=confidence,
        layout_hint=layout_hint,
        layout=layout,
    )
