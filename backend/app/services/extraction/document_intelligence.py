"""Azure Document Intelligence (prebuilt-invoice) fallback parser."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.shared.amount_sanity import plausible_money
from app.services.shared.flexible_date import parse_flexible_date
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.extraction.line_items_parser import parse_line_items_from_di_items
from app.services.master_data.vendor_name_utils import normalize_vendor_name
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MODEL_ID = "prebuilt-invoice"


def is_di_enabled() -> bool:
    return get_settings().azure_di_enabled


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return plausible_money(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_flexible_date(str(value).strip() or None)


def _field_value(field: Any) -> Any:
    if field is None:
        return None
    for attr in (
        "value_string",
        "value_date",
        "value_phone_number",
        "value_number",
    ):
        val = getattr(field, attr, None)
        if val is not None:
            return val
    currency = getattr(field, "value_currency", None)
    if currency is not None:
        amount = getattr(currency, "amount", None)
        if amount is not None:
            return amount
    address = getattr(field, "value_address", None)
    if address is not None:
        parts = [
            getattr(address, "street_address", None),
            getattr(address, "city", None),
            getattr(address, "state", None),
            getattr(address, "postal_code", None),
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    content = getattr(field, "content", None)
    return content


def _field_confidence(field: Any) -> float | None:
    """Read Azure DI field confidence when present; otherwise None."""
    if field is None:
        return None
    raw = getattr(field, "confidence", None)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _normalize_abn(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 11:
        return digits[:11]
    return None


def _map_di_document(doc: Any) -> InvoiceData:
    fields = getattr(doc, "fields", None) or {}

    def get(name: str) -> Any:
        return _field_value(fields.get(name))

    def conf(name: str) -> float | None:
        return _field_confidence(fields.get(name))

    vendor = get("VendorName") or get("VendorAddressRecipient")
    if isinstance(vendor, str):
        vendor = normalize_vendor_name(vendor.strip()) or None

    customer_name = get("CustomerName") or get("CustomerAddressRecipient")
    if isinstance(customer_name, str):
        customer_name = normalize_vendor_name(customer_name.strip()) or None

    vendor_address = get("VendorAddress")
    customer_address = get("CustomerAddress") or get("BillingAddress") or get("ShippingAddress")
    if isinstance(vendor_address, dict):
        vendor_address = _field_value(vendor_address)
    if isinstance(customer_address, dict):
        customer_address = _field_value(customer_address)

    from app.services.extraction.party_field_service import sanitize_address

    vendor_tax_raw = get("VendorTaxId")
    customer_tax_raw = get("CustomerTaxId")
    vendor_tax_id = _normalize_abn(str(vendor_tax_raw) if vendor_tax_raw else None)
    buyer_tax_id = _normalize_abn(str(customer_tax_raw) if customer_tax_raw else None)

    party_extracted: dict[str, str] = {}
    if isinstance(vendor, str) and vendor:
        party_extracted["seller_name"] = vendor
    if vendor_tax_id:
        party_extracted["seller_tax_id"] = vendor_tax_id
        party_extracted["seller_abn"] = vendor_tax_id
    if isinstance(vendor_address, str) and vendor_address.strip():
        party_extracted["seller_address"] = sanitize_address(vendor_address)
    if isinstance(customer_address, str) and customer_address.strip():
        sanitized_buyer = sanitize_address(customer_address)
        party_extracted["buyer_address"] = sanitized_buyer
        party_extracted["billing_address"] = sanitized_buyer
    if customer_name:
        party_extracted["buyer_name"] = customer_name
    if buyer_tax_id:
        party_extracted["buyer_tax_id"] = buyer_tax_id

    di_scalar_sources: dict[str, str] = {}
    field_confidence: dict[str, float | None] = {}
    field_sources: dict[str, str] = {}
    if vendor:
        di_scalar_sources["vendor"] = "VendorName" if get("VendorName") else "VendorAddressRecipient"
        field_confidence["vendor"] = conf("VendorName") if get("VendorName") else conf(
            "VendorAddressRecipient"
        )
        field_sources["vendor"] = "semantic_di"
    if vendor_tax_id:
        di_scalar_sources["abn"] = "VendorTaxId"
        field_confidence["abn"] = conf("VendorTaxId")
        field_sources["abn"] = "semantic_di"

    invoice_no = get("InvoiceId")
    secondary_no = None
    if isinstance(invoice_no, str):
        from app.services.extraction.invoice_no_sanitizer import (
            apply_invoice_no_secondary,
            sanitize_invoice_no_parts,
        )

        invoice_no, secondary_no = sanitize_invoice_no_parts(invoice_no.strip())
        party_extracted = apply_invoice_no_secondary(party_extracted, secondary_no)

    subtotal = _parse_decimal(get("SubTotal"))
    gst = _parse_decimal(get("TotalTax"))
    invoice_total = get("InvoiceTotal")
    amount_due = get("AmountDue")
    total = _parse_decimal(invoice_total if invoice_total is not None else amount_due)
    if subtotal is not None:
        di_scalar_sources["subtotal"] = "SubTotal"
        field_confidence["subtotal"] = conf("SubTotal")
        field_sources["subtotal"] = "semantic_di"
    if gst is not None:
        di_scalar_sources["gst"] = "TotalTax"
        field_confidence["gst"] = conf("TotalTax")
        field_sources["gst"] = "semantic_di"
    if total is not None:
        di_scalar_sources["total"] = "InvoiceTotal" if invoice_total is not None else "AmountDue"
        field_confidence["total"] = (
            conf("InvoiceTotal") if invoice_total is not None else conf("AmountDue")
        )
        field_sources["total"] = "semantic_di"

    currency_raw = get("CurrencyCode")
    currency = ""
    if isinstance(currency_raw, str) and currency_raw.strip():
        currency = currency_raw.strip().upper()
        di_scalar_sources["currency"] = "CurrencyCode"
        field_confidence["currency"] = conf("CurrencyCode")
        field_sources["currency"] = "semantic_di"

    raw_snapshot = {
        k: str(_field_value(v))
        for k, v in fields.items()
        if v is not None
    }

    po_ref = get("PurchaseOrder")
    if isinstance(po_ref, str):
        po_ref = po_ref.strip() or None
    else:
        po_ref = None
    if po_ref:
        di_scalar_sources["po_reference"] = "PurchaseOrder"
        field_confidence["po_reference"] = conf("PurchaseOrder")
        field_sources["po_reference"] = "semantic_di"

    project_code = get("ProjectCode")
    cost_center = get("CostCenter")
    cost_centre = None
    if isinstance(project_code, str) and project_code.strip():
        cost_centre = project_code.strip()
        di_scalar_sources["cost_centre"] = "ProjectCode"
        field_confidence["cost_centre"] = conf("ProjectCode")
        field_sources["cost_centre"] = "semantic_di"
    elif isinstance(cost_center, str) and cost_center.strip():
        cost_centre = cost_center.strip()
        di_scalar_sources["cost_centre"] = "CostCenter"
        field_confidence["cost_centre"] = conf("CostCenter")
        field_sources["cost_centre"] = "semantic_di"

    inv_date = _parse_date(get("InvoiceDate"))
    due = _parse_date(get("DueDate"))
    if invoice_no:
        di_scalar_sources["invoice_no"] = "InvoiceId"
        field_confidence["invoice_no"] = conf("InvoiceId")
        field_sources["invoice_no"] = "semantic_di"
    if inv_date:
        di_scalar_sources["invoice_date"] = "InvoiceDate"
        field_confidence["invoice_date"] = conf("InvoiceDate")
        field_sources["invoice_date"] = "semantic_di"
    if due:
        di_scalar_sources["due_date"] = "DueDate"
        field_confidence["due_date"] = conf("DueDate")
        field_sources["due_date"] = "semantic_di"
    if party_extracted.get("billing_address"):
        addr_source = "CustomerAddress"
        if get("BillingAddress"):
            addr_source = "BillingAddress"
        elif get("ShippingAddress"):
            addr_source = "ShippingAddress"
        di_scalar_sources["billing_address"] = addr_source
        field_confidence["billing_address"] = conf(addr_source)
        field_sources["billing_address"] = "semantic_di"

    line_items = parse_line_items_from_di_items(fields.get("Items"))
    line_confidences = [
        item.source_confidence for item in line_items if item.source_confidence is not None
    ]

    return InvoiceData(
        vendor=vendor if isinstance(vendor, str) else None,
        abn=vendor_tax_id,
        billing_address=party_extracted.get("billing_address"),
        invoice_no=invoice_no if isinstance(invoice_no, str) else None,
        invoice_date=inv_date,
        due_date=due,
        currency=currency,
        subtotal=subtotal,
        gst=gst,
        total=total,
        po_reference=po_ref if isinstance(po_ref, str) else None,
        cost_centre=cost_centre,
        line_items=line_items,
        extracted_fields=party_extracted,
        raw_fields={
            "azure_di": raw_snapshot,
            "di_scalar_sources": di_scalar_sources,
            "field_confidence": field_confidence,
            "field_sources": field_sources,
            "di_line_item_confidences": line_confidences,
        },
    )


def parse_with_document_intelligence_ex(
    file_path: str | Path,
    *,
    content_type: str = "application/pdf",
    model_id_override: str | None = None,
) -> tuple[InvoiceData | None, dict[str, Any] | None]:
    """
    Analyze a document with Azure DI invoice (or override) model.

    Returns (InvoiceData | None, raw_snapshot | None).
    """
    if not is_di_enabled():
        return None, None

    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        logger.warning("di_file_missing", path=str(path))
        return None, None

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        logger.error("di_sdk_missing", error=str(exc))
        return None, None

    from app.services.extraction.di_raw_persist import serialize_di_analyze_result

    model_id = (model_id_override or settings.azure_di_model_id or _MODEL_ID).strip()
    raw_snapshot: dict[str, Any] | None = None
    try:
        client = DocumentIntelligenceClient(
            settings.azure_di_endpoint.rstrip("/"),
            AzureKeyCredential(settings.azure_di_key),
        )
        with path.open("rb") as document:
            poller = client.begin_analyze_document(
                model_id,
                body=document,
                content_type=content_type,
            )
        result = poller.result()
        raw_snapshot = serialize_di_analyze_result(result)
    except Exception as exc:
        logger.warning(
            "di_analyze_failed",
            path=str(path),
            model_id=model_id,
            error=str(exc),
        )
        return None, raw_snapshot

    documents = getattr(result, "documents", None) or []
    if not documents:
        logger.warning("di_no_documents", path=str(path))
        return None, raw_snapshot

    content = (getattr(result, "content", None) or "").strip()
    data = _map_di_document(documents[0])
    if content:
        from app.services.extraction.document_text import cap_document_text
        from app.services.shared.currency import apply_currency_ocr_fallback

        capped = cap_document_text(content)
        data.document_text = capped
        data.raw_fields["document_text"] = capped
        data = apply_currency_ocr_fallback(data, capped)  # type: ignore[assignment]
    logger.info(
        "di_parse_ok",
        path=str(path),
        model_id=model_id,
        invoice_no=data.invoice_no,
    )
    return data, raw_snapshot


def parse_with_document_intelligence(
    file_path: str | Path,
    *,
    content_type: str = "application/pdf",
) -> InvoiceData | None:
    """
    Analyze a PDF with Azure prebuilt-invoice.

    Returns None if DI is not configured or the API call fails.
    """
    data, _raw = parse_with_document_intelligence_ex(
        file_path, content_type=content_type
    )
    return data


def read_pdf_page_texts_via_di(file_path: str | Path) -> list[tuple[int, str]] | None:
    """
    OCR each page with Azure prebuilt-read when local PDF text is empty.

    Returns list of (page_index, text) or None when DI is unavailable.
    """
    if not is_di_enabled():
        return None

    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        return None

    model_id = (settings.azure_di_read_model_id or "prebuilt-read").strip()
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        logger.error("di_sdk_missing", error=str(exc))
        return None

    try:
        client = DocumentIntelligenceClient(
            settings.azure_di_endpoint.rstrip("/"),
            AzureKeyCredential(settings.azure_di_key),
        )
        with path.open("rb") as document:
            poller = client.begin_analyze_document(
                model_id,
                body=document,
                content_type="application/pdf",
            )
        result = poller.result()
    except Exception as exc:
        logger.warning("di_read_failed", path=str(path), model_id=model_id, error=str(exc))
        return None

    pages_out: list[tuple[int, str]] = []
    for index, page in enumerate(getattr(result, "pages", None) or []):
        lines = [line.content for line in (getattr(page, "lines", None) or []) if line.content]
        pages_out.append((index, "\n".join(lines)))

    if not pages_out:
        logger.warning("di_read_no_pages", path=str(path))
        return None

    logger.info("di_read_ok", path=str(path), model_id=model_id, pages=len(pages_out))
    return pages_out
