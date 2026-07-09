"""One-off generator for data/field_registry.json from legacy constants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.classification.document_type_field_keys import (  # noqa: E402
    CANONICAL_EXTRACTION_FIELD_KEYS,
    POSTING_CRITICAL_FIELD_KEYS,
)
from app.services.extraction.extraction_field_values import (  # noqa: E402
    _FIELD_HINT_PATTERNS,
    _FINANCE_FIELD_DEFS,
    _PRESET_EXTRACTION_LABELS,
    extraction_field_label,
)

TAX_VARIANTS = {
    "AU": {"name": "ABN", "regex": r"^\d{11}$", "checksum": "abn_checksum"},
    "IN": {"name": "GSTIN", "regex": r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"},
    "SG": {"name": "UEN", "regex": r"^[0-9]{8,10}[A-Z]$|^[ST]\d{2}[A-Z]{2}\d{4}[A-Z]$"},
    "GB": {"name": "VAT Number", "regex": r"^[A-Z]{2}\d{8,12}$"},
    "EU": {"name": "VAT Number", "regex": r"^[A-Z]{2}\d{8,12}$"},
    "default": {"name": "Tax ID", "regex": None},
}


def _data_type(key: str) -> str:
    if key in {"subtotal", "gst", "gst_rate", "total"}:
        return "money"
    if key in {"invoice_date", "due_date"}:
        return "date"
    if key == "line_items":
        return "line_items"
    if key == "bank_details":
        return "bank"
    if key in {"document_text", "attachment_name", "document_heading", "email_subject"}:
        return "text"
    return "string"


def _category(key: str) -> str:
    if key in {"abn", "seller_abn", "buyer_abn", "seller_tax_id", "buyer_tax_id"}:
        return "party_identifier"
    if key in {"vendor", "seller_name", "buyer_name"}:
        return "party"
    if key in {"invoice_no", "po_reference", "so_reference"}:
        return "document_reference"
    if key in {"subtotal", "gst", "gst_rate", "total"}:
        return "amount"
    return "general"


def _grounding(key: str) -> bool:
    return key not in {"attachment_name", "document_text", "email_subject"}


def _source_priority(key: str) -> list[str]:
    if key == "total":
        return ["azure_di", "llm", "regex"]
    if key == "vendor":
        return ["llm", "layout_kv", "azure_di"]
    return ["llm", "azure_di", "layout_kv", "regex"]


def _confuse(key: str) -> list[str]:
    raw = _FINANCE_FIELD_DEFS.get(key, {}).get("do_not_use", "")
    out: list[str] = []
    mapping = {
        "buyer name": "buyer_name",
        "buyer tax id": "buyer_abn",
        "customername": "buyer_name",
        "bill to": "buyer_name",
        "invoice number": "invoice_no",
        "po number": "po_reference",
        "sales order": "so_reference",
    }
    for part in str(raw).split(","):
        token = part.strip().lower()
        if not token:
            continue
        norm = token.replace(" ", "_")
        if norm in CANONICAL_EXTRACTION_FIELD_KEYS:
            out.append(norm)
        elif token in mapping:
            out.append(mapping[token])
    return list(dict.fromkeys(out))


def main() -> None:
    fields: list[dict[str, object]] = []
    for key in sorted(CANONICAL_EXTRACTION_FIELD_KEYS):
        hint = _FIELD_HINT_PATTERNS.get(key, "")
        synonyms = [part.strip() for part in hint.split(",") if part.strip()] if hint else []
        fin = _FINANCE_FIELD_DEFS.get(key, {})
        entry: dict[str, object] = {
            "key": key,
            "label": _PRESET_EXTRACTION_LABELS.get(key, extraction_field_label(key)),
            "data_type": _data_type(key),
            "category": _category(key),
            "posting_critical": key in POSTING_CRITICAL_FIELD_KEYS,
            "grounding_required": _grounding(key),
            "synonyms": synonyms,
            "extraction_hint": hint or f"Look for {key.replace('_', ' ')} in document header or labeled fields",
            "finance_role": fin.get("finance_role", ""),
            "do_not_confuse_with": _confuse(key),
            "source_priority": _source_priority(key),
        }
        if key in {"abn", "seller_abn", "buyer_abn", "seller_tax_id", "buyer_tax_id"}:
            entry["jurisdiction_variants"] = TAX_VARIANTS
        fields.append(entry)

    for key, hint in [
        ("bank_bsb", "BSB"),
        ("bank_account", "Account No, Account Number"),
        ("bank_name", "Bank Name"),
    ]:
        fields.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "data_type": "bank",
                "category": "bank",
                "posting_critical": False,
                "grounding_required": True,
                "synonyms": [hint.split(",")[0]] if hint else [],
                "extraction_hint": hint,
                "finance_role": _FINANCE_FIELD_DEFS.get(key, {}).get("finance_role", ""),
                "do_not_confuse_with": _confuse(key),
                "source_priority": ["llm", "regex"],
            }
        )

    path = ROOT / "data" / "field_registry.json"
    path.write_text(json.dumps({"version": "1", "fields": fields}, indent=2), encoding="utf-8")
    print(f"Wrote {len(fields)} fields to {path}")


if __name__ == "__main__":
    main()
