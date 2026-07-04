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

    party_extracted: dict[str, str] = {}
    if isinstance(vendor_address, str) and vendor_address.strip():
        party_extracted["seller_address"] = sanitize_address(vendor_address)
    if isinstance(customer_address, str) and customer_address.strip():
        sanitized_buyer = sanitize_address(customer_address)
        party_extracted["buyer_address"] = sanitized_buyer
        party_extracted["billing_address"] = sanitized_buyer
    if customer_name:
        party_extracted["buyer_name"] = customer_name

    invoice_no = get("InvoiceId")
    if isinstance(invoice_no, str):
        invoice_no = invoice_no.strip() or None

    subtotal = _parse_decimal(get("SubTotal"))
    gst = _parse_decimal(get("TotalTax"))
    total = _parse_decimal(get("InvoiceTotal") or get("AmountDue"))

    currency = get("CurrencyCode") or "AUD"
    if isinstance(currency, str):
        currency = currency.strip().upper() or "AUD"
    else:
        currency = "AUD"

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

    cost_centre = get("ProjectCode") or get("CostCenter")
    if isinstance(cost_centre, str):
        cost_centre = cost_centre.strip() or None
    else:
        cost_centre = None

    line_items = parse_line_items_from_di_items(fields.get("Items"))

    return InvoiceData(
        vendor=vendor if isinstance(vendor, str) else None,
        abn=_normalize_abn(str(get("VendorTaxId") or get("CustomerTaxId") or "")),
        billing_address=party_extracted.get("billing_address"),
        invoice_no=invoice_no if isinstance(invoice_no, str) else None,
        invoice_date=_parse_date(get("InvoiceDate")),
        due_date=_parse_date(get("DueDate")),
        currency=currency,
        subtotal=subtotal,
        gst=gst,
        total=total,
        po_reference=po_ref if isinstance(po_ref, str) else None,
        cost_centre=cost_centre if isinstance(cost_centre, str) else None,
        line_items=line_items,
        extracted_fields=party_extracted,
        raw_fields={"azure_di": raw_snapshot},
    )


def parse_with_document_intelligence(
    file_path: str | Path,
    *,
    content_type: str = "application/pdf",
) -> InvoiceData | None:
    """
    Analyze a PDF with Azure prebuilt-invoice.

    Returns None if DI is not configured or the API call fails.
    """
    if not is_di_enabled():
        return None

    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        logger.warning("di_file_missing", path=str(path))
        return None

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        logger.error("di_sdk_missing", error=str(exc))
        return None

    model_id = settings.azure_di_model_id or _MODEL_ID
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
    except Exception as exc:
        logger.warning(
            "di_analyze_failed",
            path=str(path),
            model_id=model_id,
            error=str(exc),
        )
        return None

    documents = getattr(result, "documents", None) or []
    if not documents:
        logger.warning("di_no_documents", path=str(path))
        return None

    content = (getattr(result, "content", None) or "").strip()
    data = _map_di_document(documents[0])
    if content:
        from app.services.extraction.document_text import cap_document_text

        capped = cap_document_text(content)
        data.document_text = capped
        data.raw_fields["document_text"] = capped
    logger.info(
        "di_parse_ok",
        path=str(path),
        model_id=model_id,
        invoice_no=data.invoice_no,
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
