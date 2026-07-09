"""Unified merge of LLM, DI, layout KV, and regex extraction sources."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, TYPE_CHECKING

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.custom_field_ocr_extractors import extract_label_value_fields_from_text
from app.services.extraction.extraction_field_values import (
    apply_di_scalars_authoritative,
    clear_llm_scalars_for_di_populated_fields,
    di_scalar_field_keys,
    di_scalar_fields_populated,
    di_trusted_scalar_fields,
    effective_extraction_field_keys_for_dt,
    extracted_fields_from_parsed,
    EXTRACTED_ONLY_ATTRS,
    harvest_custom_fields_from_llm_raw,
    label_value_backfill_keys,
    merge_extracted_field_maps,
    prebuilt_invoice_scalars_active,
)
from app.services.extraction.layout_field_extractor import extract_key_value_fields
from app.services.extraction.pdf_parser import (
    parse_local_text,
    post_process_parsed_data,
)
from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text
from app.services.extraction.line_items_parser import (
    deserialize_line_items,
    di_line_items_usable,
    document_has_charge_lines,
    document_has_line_item_table,
    document_has_product_table,
    document_has_qty_only_table,
    enrich_line_items_from_text,
    enrich_parsed_line_items,
    parse_charge_lines_from_text,
    parse_line_items_from_text,
    parse_qty_only_line_items_from_text,
    resolve_line_items_from_ocr_payload,
    resolve_usable_line_items_from_payload,
    serialize_line_items,
)
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.extraction.field_grounding_service import (
    _date_grounded_in_ocr,
    _invoice_no_grounded,
    _money_grounded_in_ocr,
    ground_extracted_fields_map,
    ground_invoice_scalars,
    merge_bank_fields,
    value_grounded_in_ocr,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.master_data.vendor_name_utils import normalize_vendor_name
from app.services.shared.flexible_date import parse_flexible_date
from app.utils.abn_validator import storage_abn

if TYPE_CHECKING:
    from app.schemas.ocr_artifact import OcrArtifact


_SCALAR_FILL_FIELDS = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "subtotal",
    "gst",
    "gst_rate",
    "total",
    "currency",
    "billing_address",
    "bank_bsb",
    "bank_account",
    "cost_centre",
    "document_heading",
)

_NON_INVOICE_DI_PROFILES = frozenset(
    {
        "supporting",
        "reconciliation",
    }
)


def should_run_prebuilt_invoice_di(
    confirmed_dt: str,
    dt_definition: DocumentTypeDefinition | None,
) -> bool:
    if dt_definition is None:
        return True
    from app.services.classification.document_type_catalog import (
        _org_uses_shipped_classification_metadata,
        _shipped_defaults_lookup_code,
        playbook_profile_for_dt,
    )

    profile = playbook_profile_for_dt(dt_definition)
    shipped_lookup = _shipped_defaults_lookup_code(dt_definition.code, dt_definition)
    repurposed = not _org_uses_shipped_classification_metadata(dt_definition, shipped_lookup)
    if repurposed and (not profile or profile in _NON_INVOICE_DI_PROFILES):
        return False
    if profile in _NON_INVOICE_DI_PROFILES:
        return False
    purchase_role = (dt_definition.purchase_bundle_role or "").strip().lower()
    sales_role = (dt_definition.sales_bundle_role or "").strip().lower()
    if purchase_role in {"po", "grn"} or sales_role in {"so", "dn"}:
        return False
    if profile == "supporting":
        return False
    return True


def _scalar_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def invoice_data_to_payload_fields(data: InvoiceData) -> dict[str, Any]:
    return {
        "vendor": data.vendor,
        "abn": data.abn,
        "invoice_no": data.invoice_no,
        "invoice_date": data.invoice_date.isoformat() if data.invoice_date else None,
        "due_date": data.due_date.isoformat() if data.due_date else None,
        "po_reference": data.po_reference,
        "subtotal": str(data.subtotal) if data.subtotal is not None else None,
        "gst": str(data.gst) if data.gst is not None else None,
        "total": str(data.total) if data.total is not None else None,
        "currency": data.currency,
        "cost_centre": data.cost_centre,
        "billing_address": data.billing_address,
        "line_items": serialize_line_items(data.line_items),
        "line_items_count": len(data.line_items),
    }


def invoice_data_from_payload_fields(raw: dict[str, Any] | None) -> InvoiceData | None:
    if not raw:
        return None
    invoice_date = raw.get("invoice_date")
    due_date = raw.get("due_date")
    if isinstance(invoice_date, date):
        inv_date = invoice_date
    else:
        inv_date = parse_flexible_date(str(invoice_date) if invoice_date else None)
    if isinstance(due_date, date):
        due = due_date
    else:
        due = parse_flexible_date(str(due_date) if due_date else None)

    invoice_no_raw = str(raw.get("invoice_no")).strip() if raw.get("invoice_no") else None
    if invoice_no_raw:
        from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no

        invoice_no_raw = sanitize_invoice_no(invoice_no_raw)

    return InvoiceData(
        vendor=(raw.get("vendor") or None),
        abn=storage_abn(str(raw.get("abn") or "").strip() or None),
        invoice_no=invoice_no_raw,
        invoice_date=inv_date,
        due_date=due,
        po_reference=(str(raw.get("po_reference")).strip() if raw.get("po_reference") else None),
        subtotal=_parse_decimal(raw.get("subtotal")),
        gst=_parse_decimal(raw.get("gst")),
        total=_parse_decimal(raw.get("total")),
        currency=(str(raw.get("currency") or "").strip().upper() or ""),
        cost_centre=(str(raw.get("cost_centre")).strip() if raw.get("cost_centre") else None),
        billing_address=(str(raw.get("billing_address")).strip() if raw.get("billing_address") else None),
        line_items=deserialize_line_items(raw.get("line_items")),
        raw_fields={"source": "di_payload"},
    )


_DI_MERGE_KEYS: frozenset[str] = frozenset(
    {
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "subtotal",
        "gst",
        "gst_rate",
        "total",
        "cost_centre",
        "billing_address",
        "line_items",
        "bank_details",
        "document_heading",
    }
)


def _configured_key_set(
    dt_definition: DocumentTypeDefinition | None,
) -> set[str]:
    if dt_definition is None:
        return set()
    return set(
        effective_extraction_field_keys_for_dt([dt_definition], dt_definition.code)
    )


def _field_configured(field_name: str, configured: set[str]) -> bool:
    if not configured:
        return True
    if field_name in configured:
        return True
    if field_name in ("bank_bsb", "bank_account", "bank_name") and "bank_details" in configured:
        return True
    return False


def _value_grounded_for_field(field_name: str, value: object, ocr_text: str | None) -> bool:
    if _scalar_empty(value):
        return False
    if field_name in ("subtotal", "gst", "total", "gst_rate"):
        amount = value if isinstance(value, Decimal) else _parse_decimal(value)
        return _money_grounded_in_ocr(amount, ocr_text, field_key=field_name)
    if field_name in ("invoice_date", "due_date"):
        if isinstance(value, date):
            return _date_grounded_in_ocr(value, ocr_text)
        parsed = parse_flexible_date(str(value))
        return _date_grounded_in_ocr(parsed, ocr_text) if parsed else False
    return value_grounded_in_ocr(str(value), ocr_text)


def _merge_di_grounded(
    primary: InvoiceData,
    secondary: InvoiceData,
    ocr_text: str | None,
) -> InvoiceData:
    """Fill empty primary fields from DI only when values are OCR-grounded."""
    updates: dict[str, object] = {}
    for field_name in (
        "vendor",
        "abn",
        "billing_address",
        "bank_bsb",
        "bank_account",
        "invoice_no",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "gst",
        "total",
        "po_reference",
        "cost_centre",
        "document_heading",
    ):
        current = getattr(primary, field_name, None)
        fallback = getattr(secondary, field_name, None)
        if not _scalar_empty(current) or _scalar_empty(fallback):
            continue
        if not _value_grounded_for_field(field_name, fallback, ocr_text):
            continue
        if field_name == "vendor":
            updates[field_name] = normalize_vendor_name(str(fallback)) or fallback
        elif field_name == "abn":
            updates[field_name] = storage_abn(str(fallback))
        else:
            updates[field_name] = fallback
    if not updates:
        return primary
    return replace(primary, **updates)


def _apply_layout_kv(
    data: InvoiceData,
    kv: dict[str, str],
    *,
    configured: set[str],
    ocr_text: str | None = None,
    skip_fields: frozenset[str] | None = None,
) -> InvoiceData:
    if not kv:
        return data
    skip = skip_fields or frozenset()
    updates: dict[str, object] = {}
    if _field_configured("vendor", configured) and "vendor" not in skip and kv.get("vendor") and _scalar_empty(data.vendor):
        candidate = normalize_vendor_name(kv["vendor"]) or kv["vendor"]
        if _value_grounded_for_field("vendor", candidate, ocr_text):
            updates["vendor"] = candidate
    if _field_configured("abn", configured) and "abn" not in skip and kv.get("abn") and _scalar_empty(data.abn):
        candidate = storage_abn(kv["abn"])
        if candidate and _value_grounded_for_field("abn", candidate, ocr_text):
            updates["abn"] = candidate
    if _field_configured("invoice_no", configured) and "invoice_no" not in skip and kv.get("invoice_no") and _scalar_empty(data.invoice_no):
        from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no

        candidate = sanitize_invoice_no(kv["invoice_no"].strip())
        if candidate and _value_grounded_for_field("invoice_no", candidate, ocr_text):
            updates["invoice_no"] = candidate
    if _field_configured("po_reference", configured) and "po_reference" not in skip and kv.get("po_reference") and _scalar_empty(data.po_reference):
        candidate = kv["po_reference"].strip()
        if _value_grounded_for_field("po_reference", candidate, ocr_text):
            updates["po_reference"] = candidate
    if _field_configured("invoice_date", configured) and "invoice_date" not in skip and kv.get("invoice_date") and data.invoice_date is None:
        parsed = parse_flexible_date(kv["invoice_date"])
        if parsed and _date_grounded_in_ocr(parsed, ocr_text):
            updates["invoice_date"] = parsed
    if _field_configured("due_date", configured) and "due_date" not in skip and kv.get("due_date") and data.due_date is None:
        parsed = parse_flexible_date(kv["due_date"])
        if parsed and _date_grounded_in_ocr(parsed, ocr_text):
            updates["due_date"] = parsed
    for money_key in ("subtotal", "gst", "gst_rate", "total"):
        if money_key in skip:
            continue
        if not _field_configured(money_key, configured):
            continue
        if kv.get(money_key) and getattr(data, money_key) is None:
            if money_key == "gst_rate":
                from app.services.extraction.gst_rate import parse_gst_rate_percent

                parsed_rate = parse_gst_rate_percent(kv[money_key])
                if parsed_rate is not None and _value_grounded_for_field(money_key, parsed_rate, ocr_text):
                    updates[money_key] = parsed_rate
            else:
                amount = _parse_decimal(kv[money_key])
                if amount is not None and _value_grounded_for_field(money_key, amount, ocr_text):
                    updates[money_key] = amount

    raw_fields = dict(data.raw_fields or {})
    raw_fields["layout_kv"] = kv
    updates["raw_fields"] = raw_fields
    if updates:
        return replace(data, **updates)
    return data


def _apply_configured_extracted_fields(
    data: InvoiceData,
    kv: dict[str, str],
    *,
    configured: set[str],
    ocr_text: str | None = None,
) -> InvoiceData:
    """Merge layout/OCR KV values into extracted_fields for configured extracted-only keys."""
    if not kv or not configured:
        return data
    extracted = dict(extracted_fields_from_parsed(data))
    updates: dict[str, str] = {}
    for key in EXTRACTED_ONLY_ATTRS:
        if not _field_configured(key, configured):
            continue
        if extracted.get(key):
            continue
        candidate = (kv.get(key) or "").strip()
        if not candidate:
            continue
        if ocr_text and not value_grounded_in_ocr(candidate, ocr_text):
            continue
        updates[key] = candidate
    if not updates:
        return data
    return replace(data, extracted_fields=merge_extracted_field_maps(extracted, updates))


def _apply_absent_fields(
    data: InvoiceData,
    dt_definition: DocumentTypeDefinition | None,
) -> InvoiceData:
    if dt_definition is None:
        return data
    absent = {str(f).strip().lower() for f in (dt_definition.absent_fields or []) if str(f).strip()}
    if not absent:
        return data

    updates: dict[str, object] = {}
    scalar_map = {
        "vendor": "vendor",
        "abn": "abn",
        "invoice_no": "invoice_no",
        "invoice_date": "invoice_date",
        "due_date": "due_date",
        "po_reference": "po_reference",
        "subtotal": "subtotal",
        "gst": "gst",
        "total": "total",
        "cost_centre": "cost_centre",
        "billing_address": "billing_address",
        "bank_bsb": "bank_bsb",
        "bank_account": "bank_account",
        "line_items": "line_items",
    }
    for key in absent:
        attr = scalar_map.get(key)
        if attr == "line_items":
            updates["line_items"] = []
        elif attr and hasattr(data, attr):
            updates[attr] = None

    extracted = dict(extracted_fields_from_parsed(data))
    for key in absent:
        extracted.pop(key, None)
    if extracted != extracted_fields_from_parsed(data):
        updates["extracted_fields"] = extracted

    if updates:
        return replace(data, **updates)
    return data


def _persist_auxiliary_fields(data: InvoiceData, local_raw: dict[str, Any]) -> InvoiceData:
    extracted = merge_extracted_field_maps(extracted_fields_from_parsed(data))
    if local_raw.get("grn_reference"):
        extracted["grn_reference"] = str(local_raw["grn_reference"])
    if local_raw.get("gstin"):
        extracted["gstin"] = str(local_raw["gstin"])
    raw_fields = dict(data.raw_fields or {})
    if local_raw.get("gstin"):
        raw_fields["gstin"] = local_raw["gstin"]
    if not extracted and not raw_fields.get("gstin"):
        return data
    return replace(
        data,
        extracted_fields=extracted or data.extracted_fields,
        raw_fields=raw_fields,
    )


def _configured_scalar_fill_fields(
    dt_definition: DocumentTypeDefinition | None,
) -> tuple[str, ...]:
    if dt_definition is None:
        return _SCALAR_FILL_FIELDS
    configured = _configured_key_set(dt_definition)
    allowed: list[str] = []
    for field_name in _SCALAR_FILL_FIELDS:
        if _field_configured(field_name, configured):
            allowed.append(field_name)
    return tuple(allowed)


def _di_grounding_skip_keys(data: InvoiceData, ocr_text: str | None, di_populated: set[str]) -> frozenset[str]:
    """DI-populated keys that survive OCR grounding — skip re-clearing those."""
    skip: set[str] = set()
    for key in di_populated:
        if key == "invoice_no":
            current = data.invoice_no
            if current and _invoice_no_grounded(str(current), ocr_text):
                skip.add(key)
        elif key in ("po_reference", "cost_centre", "vendor", "billing_address", "document_heading"):
            current = getattr(data, key, None)
            if current and value_grounded_in_ocr(str(current), ocr_text):
                skip.add(key)
        elif key == "invoice_date" and data.invoice_date is not None and _date_grounded_in_ocr(
            data.invoice_date, ocr_text
        ):
            skip.add(key)
        elif key == "due_date" and data.due_date is not None and _date_grounded_in_ocr(
            data.due_date, ocr_text
        ):
            skip.add(key)
        elif key in ("subtotal", "gst", "total"):
            current = getattr(data, key, None)
            if current is not None and _money_grounded_in_ocr(current, ocr_text, field_key=key):
                skip.add(key)
        elif key == "currency":
            currency = (data.currency or "").strip()
            if currency and value_grounded_in_ocr(currency, ocr_text):
                skip.add(key)
        elif key == "abn":
            abn_raw = (data.abn or "").strip()
            if abn_raw and value_grounded_in_ocr(abn_raw, ocr_text):
                skip.add(key)
    return frozenset(skip)


def _llm_line_items_trusted(items: list[ParsedLineItem], ocr_text: str | None) -> bool:
    """True when every LLM line item has a full qty/price/amount (prefer over DI table)."""
    _ = ocr_text
    if not items:
        return False
    for item in items:
        if not (item.description or "").strip():
            return False
        if item.qty is None or item.unit_price is None or item.amount is None:
            return False
    return True


def _qty_only_llm_rows_usable(items: list[ParsedLineItem]) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_sanitizer import _passes_minimum_product_row

    return [item for item in items if _passes_minimum_product_row(item, allow_qty_only=True)]


def _merge_line_items_from_sources(
    merged: InvoiceData,
    text: str,
    payload_dict: dict[str, object],
) -> list[ParsedLineItem]:
    """Resolve line items from DI, layout, OCR text, LLM, or charge blocks."""
    qty_only_table = document_has_qty_only_table(text, payload_dict)
    usable_di = (
        resolve_usable_line_items_from_payload(payload_dict)
        if di_line_items_usable(payload_dict)
        else []
    )
    if usable_di and not _llm_line_items_trusted(merged.line_items, text):
        return list(usable_di)

    if qty_only_table:
        llm_rows = _qty_only_llm_rows_usable(list(merged.line_items))
        if llm_rows:
            return llm_rows
        table_rows = resolve_usable_line_items_from_payload(payload_dict, allow_qty_only=True)
        if not table_rows:
            table_rows = list(
                enrich_parsed_line_items(
                    deserialize_line_items(payload_dict.get("table_line_items"))
                )
            )
            table_rows = _qty_only_llm_rows_usable(table_rows)
        if table_rows:
            return table_rows
        text_rows = parse_qty_only_line_items_from_text(text)
        return text_rows if text_rows else []

    if document_has_product_table(text, payload_dict):
        llm_rows = list(merged.line_items)
        if llm_rows:
            enriched = enrich_line_items_from_text(llm_rows, text)
            if enriched:
                return list(enriched)
        table_rows = resolve_usable_line_items_from_payload(payload_dict)
        if table_rows:
            return list(table_rows)
        text_rows = parse_line_items_from_text(text)
        if text_rows:
            return list(enrich_parsed_line_items(text_rows))
        return []

    if document_has_charge_lines(text):
        return parse_charge_lines_from_text(text) or list(merged.line_items)

    return []


def merge_extraction_sources(
    parsed: InvoiceData,
    ocr: OcrArtifact,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    di_data: InvoiceData | None = None,
) -> InvoiceData:
    """Merge LLM/DI/layout/regex into one InvoiceData with DT-aware cleanup."""
    text = (ocr.text or parsed.document_text or "").strip()
    merged = parsed
    configured_keys = _configured_key_set(dt_definition)
    if text and not (merged.document_text or "").strip():
        merged = replace(merged, document_text=text)

    payload = ocr.payload_json or {}
    di_active = prebuilt_invoice_scalars_active(payload)
    di_populated = di_scalar_fields_populated(payload) if di_active else set()
    selected_keys_list = (
        list(configured_keys)
        if configured_keys
        else list(effective_extraction_field_keys_for_dt([dt_definition], dt_definition.code))
        if dt_definition
        else []
    )
    di_trusted = (
        di_trusted_scalar_fields(payload, text, selected_keys_list)
        if di_active and text
        else set()
    )

    if di_active and not di_populated:
        di_active = False

    if not di_active:
        di_from_payload = invoice_data_from_payload_fields(payload.get("invoice_fields"))
        di_candidate = di_data or di_from_payload
        if di_candidate is not None and (not configured_keys or configured_keys & _DI_MERGE_KEYS):
            merged = _merge_di_grounded(merged, di_candidate, text)

    kv = dict(ocr.layout_kv or {})
    if text:
        kv_from_text = extract_key_value_fields(None, text)
        for key, value in kv_from_text.items():
            kv.setdefault(key, value)
    skip_layout = frozenset(di_trusted)
    merged = _apply_layout_kv(
        merged,
        kv,
        configured=configured_keys,
        ocr_text=text,
        skip_fields=skip_layout,
    )
    merged = _apply_configured_extracted_fields(
        merged,
        kv,
        configured=configured_keys,
        ocr_text=text,
    )

    from app.services.extraction.finance_field_labels import MONEY_SCALAR_KEYS
    from app.services.extraction.money_scalar_resolver import (
        extract_money_scalars_from_payload_tables,
        extract_money_scalars_from_text,
    )

    if text:
        money_keys = [
            key
            for key in MONEY_SCALAR_KEYS
            if key != "gst_rate" and _field_configured(key, configured_keys)
        ]
        if money_keys:
            money_candidates: dict[str, Decimal] = {}
            money_candidates.update(extract_money_scalars_from_payload_tables(payload, keys=money_keys))
            money_candidates.update(extract_money_scalars_from_text(text, keys=money_keys))
            money_fill: dict[str, object] = {}
            for key, amount in money_candidates.items():
                if key in di_trusted:
                    continue
                current = getattr(merged, key, None)
                if not _scalar_empty(current):
                    continue
                if _value_grounded_for_field(key, amount, text):
                    money_fill[key] = amount
            if money_fill:
                merged = replace(merged, **money_fill)

    if text:
        local = parse_local_text(text)
        llm_bsb = merged.bank_bsb
        llm_account = merged.bank_account
        fill: dict[str, object] = {}
        for field_name in _configured_scalar_fill_fields(dt_definition):
            if field_name in di_trusted:
                continue
            current = getattr(merged, field_name, None)
            fallback = getattr(local, field_name, None)
            if _scalar_empty(current) and not _scalar_empty(fallback):
                if _value_grounded_for_field(field_name, fallback, text):
                    fill[field_name] = fallback
        merged_items = list(merged.line_items)
        merge_line_items = not configured_keys or "line_items" in configured_keys
        if merge_line_items:
            payload_dict = dict(ocr.payload_json or {})
            qty_only_table = document_has_qty_only_table(text, payload_dict)
            allow_qty_only = qty_only_table
            merged_items = _merge_line_items_from_sources(merged, text, payload_dict)
            merged_items = sanitize_line_items(
                merged_items,
                ocr_text=text,
                extracted_fields=merged.extracted_fields,
                vendor=merged.vendor,
                invoice_no=merged.invoice_no,
                po_reference=merged.po_reference,
                so_reference=(merged.extracted_fields or {}).get("so_reference"),
                cost_centre=merged.cost_centre,
                allow_qty_only=allow_qty_only,
            )
            if merged_items != merged.line_items:
                fill["line_items"] = merged_items
        bank_bsb, bank_account = merge_bank_fields(
            llm_bsb=llm_bsb,
            llm_account=llm_account,
            regex_bsb=local.bank_bsb if _field_configured("bank_bsb", configured_keys) else None,
            regex_account=local.bank_account if _field_configured("bank_account", configured_keys) else None,
            ocr_text=text,
        )
        if bank_bsb != merged.bank_bsb:
            fill["bank_bsb"] = bank_bsb
        if bank_account != merged.bank_account:
            fill["bank_account"] = bank_account
        if fill:
            merged = replace(merged, **fill)
        merged = _persist_auxiliary_fields(merged, local.raw_fields)

    permit_fields = (
        extract_permit_fields_from_text(text)
        if text and configured_keys & {"permit_no", "consignment_ref"}
        else {}
    )
    backfill_keys = label_value_backfill_keys(selected_keys_list, parsed=merged)
    ocr_label_fields = extract_label_value_fields_from_text(text, backfill_keys) if text else {}
    ocr_label_fields = ground_extracted_fields_map(
        ocr_label_fields,
        text,
        requested_keys=backfill_keys,
    )
    merged_extracted = merge_extracted_field_maps(
        extracted_fields_from_parsed(merged),
        permit_fields,
        ocr_label_fields,
    )
    if merged_extracted:
        merged = replace(merged, extracted_fields=merged_extracted)
    elif not merged.extracted_fields and text:
        local = parse_local_text(text)
        custom = harvest_custom_fields_from_llm_raw(local.raw_fields)
        if custom:
            merged = replace(merged, extracted_fields=custom)

    merged = post_process_parsed_data(merged, text, dt_definition=dt_definition)
    if di_trusted:
        merged = apply_di_scalars_authoritative(
            merged, payload, selected_keys_list, ocr_text=text
        )
    merged = ground_invoice_scalars(
        merged,
        text,
        skip_keys=_di_grounding_skip_keys(merged, text, di_trusted),
    )
    merged = _apply_absent_fields(merged, dt_definition)

    from app.services.extraction.party_field_service import sanitize_address

    if merged.billing_address:
        merged = replace(merged, billing_address=sanitize_address(merged.billing_address) or None)
    party_addr = (merged.extracted_fields or {}).get("buyer_address")
    if party_addr and not merged.billing_address:
        merged = replace(merged, billing_address=sanitize_address(party_addr) or None)

    from app.config import flag_enabled_for_dt, get_settings
    from app.services.extraction.merge_disagreement_telemetry import (
        collect_scalar_disagreements,
        disagreement_audit_detail,
    )

    dt_code = (dt_definition.code or "").strip().upper() if dt_definition else ""
    local_for_telemetry = parse_local_text(text) if text else None
    disagreement_rows = collect_scalar_disagreements(
        field_keys=selected_keys_list,
        llm_parsed=parsed,
        di_parsed=di_data,
        regex_parsed=local_for_telemetry,
        merged=merged,
    )
    if disagreement_rows:
        raw = dict(merged.raw_fields or {})
        raw["_merge_source_disagreement"] = disagreement_audit_detail(disagreement_rows)
        merged = replace(merged, raw_fields=raw)

    settings = get_settings()
    if settings.use_field_fusion and dt_code and flag_enabled_for_dt("use_field_fusion", dt_code):
        from app.services.extraction.field_fusion_engine import (
            apply_fusion_to_invoice_data,
            fuse_scalar_fields,
        )

        sources_by_field: dict[str, dict[str, object]] = {}
        for key in selected_keys_list:
            if key == "line_items":
                continue
            field_sources: dict[str, object] = {}
            for source_name, source_parsed in (
                ("llm", parsed),
                ("azure_di", di_data),
                ("regex", local_for_telemetry),
            ):
                if source_parsed is None:
                    continue
                value = getattr(source_parsed, key, None)
                if value is not None and str(value).strip():
                    field_sources[source_name] = value
            if field_sources:
                sources_by_field[key] = field_sources
        fused = fuse_scalar_fields(
            sources_by_field,
            dt_definition=dt_definition,
            field_keys=selected_keys_list,
        )
        merged = apply_fusion_to_invoice_data(merged, fused)

    return merged
