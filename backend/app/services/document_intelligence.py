"""Azure Document Intelligence (prebuilt-invoice) fallback parser."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.line_items_parser import parse_line_items_from_di_items
from app.services.vendor_name_utils import normalize_vendor_name
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MODEL_ID = "prebuilt-invoice"


def is_di_enabled() -> bool:
    return get_settings().azure_di_enabled


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


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

    data = _map_di_document(documents[0])
    logger.info(
        "di_parse_ok",
        path=str(path),
        model_id=model_id,
        invoice_no=data.invoice_no,
    )
    return data
