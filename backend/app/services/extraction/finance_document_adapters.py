"""Adapters between InvoiceData and FinanceDocumentNormalized."""

from __future__ import annotations

from app.schemas.finance_document import FinanceDocumentNormalized, FinanceLineItem
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.routes import ExtractionRoute
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

_INVOICE_LIKE = frozenset(
    {
        ExtractionRoute.INVOICE,
        ExtractionRoute.CREDIT_NOTE,
        ExtractionRoute.DEBIT_NOTE,
        ExtractionRoute.EXPENSE_CLAIM,
        ExtractionRoute.RECEIPT,
    }
)


def _document_number_for_route(data: InvoiceData, route: str) -> str | None:
    extracted = data.extracted_fields or {}
    if route == ExtractionRoute.PURCHASE_ORDER.value:
        return data.po_reference or data.invoice_no or extracted.get("po_reference")
    if route == ExtractionRoute.GRN.value:
        return (
            extracted.get("grn_reference")
            or data.invoice_no
            or data.po_reference
        )
    if route == ExtractionRoute.REMITTANCE.value:
        return data.invoice_no or extracted.get("remittance_reference")
    if route == ExtractionRoute.STATEMENT.value:
        return data.invoice_no or extracted.get("statement_reference")
    return data.invoice_no


def _amount_due_for_route(data: InvoiceData, route: str):
    # Statements often show closing balance as "total" — don't treat as amount_due.
    if route in {
        ExtractionRoute.STATEMENT.value,
        ExtractionRoute.SUPPORTING_DOCUMENT.value,
        ExtractionRoute.UNKNOWN.value,
        ExtractionRoute.PURCHASE_ORDER.value,
        ExtractionRoute.GRN.value,
    }:
        return None
    if route == ExtractionRoute.REMITTANCE.value:
        return data.total
    return data.total


def _reference_numbers(data: InvoiceData, route: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    extracted = data.extracted_fields or {}
    if data.po_reference:
        refs["po_reference"] = data.po_reference
    if data.cost_centre:
        refs["cost_centre"] = data.cost_centre
    for key in (
        "grn_reference",
        "so_reference",
        "remittance_reference",
        "statement_reference",
        "statement_period",
    ):
        value = extracted.get(key)
        if value:
            refs[key] = str(value)
    if route == ExtractionRoute.PURCHASE_ORDER.value and data.invoice_no and "po_reference" not in refs:
        refs["document_number_alias"] = data.invoice_no
    return refs


def _payment_details(data: InvoiceData, route: str) -> dict[str, str]:
    payment: dict[str, str] = {}
    if data.bank_bsb:
        payment["bank_bsb"] = data.bank_bsb
    if data.bank_account:
        payment["bank_account"] = data.bank_account
    if route == ExtractionRoute.REMITTANCE.value and data.total is not None:
        payment["amount_paid"] = str(data.total)
    return payment


def finance_document_from_invoice_data(
    data: InvoiceData,
    *,
    decision: DocumentRouteDecision | None = None,
    source_model: str | None = None,
    review_reasons: list[str] | None = None,
) -> FinanceDocumentNormalized:
    raw = data.raw_fields or {}
    field_confidence = dict(raw.get("field_confidence") or {})
    field_sources = dict(raw.get("field_sources") or {})
    parties = {
        k: v
        for k, v in (data.extracted_fields or {}).items()
        if k
        in {
            "seller_name",
            "buyer_name",
            "seller_address",
            "buyer_address",
            "seller_tax_id",
            "buyer_tax_id",
            "seller_abn",
            "billing_address",
        }
        and v
    }

    route = decision.route.value if decision else ExtractionRoute.INVOICE.value
    confidences = [c for c in field_confidence.values() if isinstance(c, (int, float))]
    line_confidences = [
        item.source_confidence
        for item in data.line_items
        if item.source_confidence is not None
    ]
    source_confidence = None
    if confidences:
        source_confidence = min(confidences)
    elif line_confidences:
        source_confidence = min(line_confidences)

    # Invoice-like + remittance: full money semantics. Statement: closing balance as total only.
    # PO/GRN/supporting: keep total if extracted, but never invent amount_due / tax splits.
    invoice_like = route in {r.value for r in _INVOICE_LIKE}
    include_tax_split = invoice_like
    include_total = invoice_like or route in {
        ExtractionRoute.REMITTANCE.value,
        ExtractionRoute.STATEMENT.value,
        ExtractionRoute.PURCHASE_ORDER.value,
        ExtractionRoute.GRN.value,
    }

    return FinanceDocumentNormalized(
        document_type=route,
        vendor_name=data.vendor,
        buyer_name=(data.extracted_fields or {}).get("buyer_name"),
        document_number=_document_number_for_route(data, route),
        document_date=data.invoice_date,
        due_date=data.due_date if invoice_like else None,
        currency=data.currency or None,
        subtotal=data.subtotal if include_tax_split else None,
        tax=data.gst if include_tax_split else None,
        total=data.total if include_total else None,
        amount_due=_amount_due_for_route(data, route),
        reference_numbers=_reference_numbers(data, route),
        line_items=[
            FinanceLineItem(
                description=item.description,
                qty=item.qty,
                unit_price=item.unit_price,
                amount=item.amount,
                tax_amount=item.tax_amount if include_tax_split else None,
                source=item.source,
                source_confidence=item.source_confidence,
            )
            for item in data.line_items
        ],
        parties=parties,
        payment_details=_payment_details(data, route),
        source_model=source_model,
        source_confidence=source_confidence,
        field_confidence=field_confidence,
        field_sources=field_sources,
        review_reasons=list(review_reasons or (decision.review_hints if decision else ())),
        confirmed_dt=decision.confirmed_dt if decision else None,
        extraction_route=route,
    )


def invoice_data_from_finance_document(doc: FinanceDocumentNormalized) -> InvoiceData:
    extracted = dict(doc.parties)
    if doc.vendor_name:
        extracted.setdefault("seller_name", doc.vendor_name)
    if doc.buyer_name:
        extracted.setdefault("buyer_name", doc.buyer_name)
    for key, value in (doc.reference_numbers or {}).items():
        if key in {"grn_reference", "so_reference", "remittance_reference", "statement_reference", "statement_period"}:
            extracted[key] = value

    route = (doc.extraction_route or doc.document_type or "").strip().lower()
    invoice_no = doc.document_number
    po_reference = doc.reference_numbers.get("po_reference")
    if route == ExtractionRoute.PURCHASE_ORDER.value:
        po_reference = po_reference or doc.document_number
        # Keep invoice_no empty unless it was a distinct alias
        invoice_no = doc.reference_numbers.get("document_number_alias")

    line_items = [
        ParsedLineItem(
            description=item.description,
            qty=item.qty,
            unit_price=item.unit_price,
            amount=item.amount,
            tax_amount=item.tax_amount,
            source=item.source,
            source_confidence=item.source_confidence,
        )
        for item in doc.line_items
    ]
    return InvoiceData(
        vendor=doc.vendor_name,
        abn=doc.parties.get("seller_abn") or doc.parties.get("seller_tax_id"),
        billing_address=doc.parties.get("billing_address") or doc.parties.get("buyer_address"),
        bank_bsb=doc.payment_details.get("bank_bsb"),
        bank_account=doc.payment_details.get("bank_account"),
        invoice_no=invoice_no,
        invoice_date=doc.document_date,
        due_date=doc.due_date,
        currency=doc.currency or "",
        subtotal=doc.subtotal,
        gst=doc.tax,
        total=doc.total if doc.total is not None else doc.amount_due,
        po_reference=po_reference,
        cost_centre=doc.reference_numbers.get("cost_centre"),
        line_items=line_items,
        extracted_fields=extracted,
        raw_fields={
            "finance_document": doc.model_dump_jsonable(),
            "field_confidence": dict(doc.field_confidence),
            "field_sources": dict(doc.field_sources),
        },
    )


def attach_finance_document_to_payload(
    payload: dict[str, object],
    invoice_data: InvoiceData,
    *,
    decision: DocumentRouteDecision,
    source_model: str | None = None,
) -> None:
    doc = finance_document_from_invoice_data(
        invoice_data,
        decision=decision,
        source_model=source_model,
        review_reasons=list(decision.review_hints),
    )
    payload["finance_document"] = doc.model_dump_jsonable()
    if invoice_data.raw_fields is not None:
        invoice_data.raw_fields["finance_document"] = doc.model_dump_jsonable()


def invoice_data_from_layout_payload(
    ocr_payload: dict[str, object],
    *,
    text: str = "",
    layout_kv: dict[str, str] | None = None,
) -> InvoiceData:
    """Build a lightweight InvoiceData snapshot from layout OCR payload."""
    from app.services.extraction.line_items_parser import (
        document_has_qty_only_table,
        resolve_line_items_for_strategy,
    )
    from app.services.extraction.line_items_sanitizer import sanitize_line_items

    layout_mode = str(ocr_payload.get("layout_line_mode") or "gap_fill").strip().lower()
    allow_qty_only = layout_mode == "primary" or document_has_qty_only_table(text, ocr_payload)
    items = resolve_line_items_for_strategy(
        ocr_payload,
        layout_mode=layout_mode,
        allow_qty_only=allow_qty_only,
    )
    # ignore + empty DI: still surface printed layout grids (money or qty-only).
    if not items and layout_mode == "ignore":
        items = resolve_line_items_for_strategy(
            ocr_payload,
            layout_mode="primary",
            allow_qty_only=True,
        )

    kv = layout_kv or {}
    if isinstance(ocr_payload.get("layout_kv"), dict):
        kv = {**dict(ocr_payload["layout_kv"]), **kv}  # type: ignore[arg-type]

    extracted: dict[str, str] = {}
    for key in ("grn_reference", "so_reference", "po_reference", "remittance_reference"):
        for label, value in kv.items():
            if key.replace("_", " ") in label.lower() or key in label.lower():
                extracted[key] = str(value).strip()
                break

    items = sanitize_line_items(
        list(items),
        extracted_fields=extracted,
        po_reference=extracted.get("po_reference"),
        so_reference=extracted.get("so_reference"),
        allow_qty_only=allow_qty_only or layout_mode in {"primary", "ignore"},
    )

    field_sources = {
        "line_items": "layout_table" if items else "layout_kv",
    }
    field_confidence: dict[str, float | None] = {
        "line_items": None,
    }
    line_conf = [i.source_confidence for i in items if i.source_confidence is not None]
    if line_conf:
        field_confidence["line_items"] = min(line_conf)

    return InvoiceData(
        document_text=text or None,
        line_items=list(items),
        extracted_fields=extracted,
        po_reference=extracted.get("po_reference"),
        raw_fields={
            "field_sources": field_sources,
            "field_confidence": field_confidence,
        },
    )
