"""Extend document_type_defaults.json with machine catalog metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_NEGATIVE = [
    "Certificate of Origin",
    "Packing List",
    "Bill of Lading",
    "Cargo Clearance Permit",
]

INVOICE_CROSS_RULES = [
    "sum(line_items.amount) == subtotal",
    "subtotal + gst == total",
]

DT_META: dict[str, dict[str, object]] = {
    "DT-01": {
        "classification_hints": ["Tax Invoice", "PO goods invoice", "Purchase Order goods"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": INVOICE_CROSS_RULES,
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
        "field_overrides": {"total": {"source_priority": ["azure_di", "llm", "regex"]}},
    },
    "DT-02": {
        "classification_hints": ["Purchase Order", "PO copy", "PO (supporting)"],
        "negative_hints": ["Tax Invoice"],
        "cross_field_rules": [],
        "azure_di_profile": "",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-04": {
        "classification_hints": ["Credit Note", "Credit Memo"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": INVOICE_CROSS_RULES,
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-05": {
        "classification_hints": ["Debit Note"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": INVOICE_CROSS_RULES,
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-07": {
        "classification_hints": ["Tax Invoice", "Invoice"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": INVOICE_CROSS_RULES,
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-08": {
        "classification_hints": ["Direct expense", "Expense invoice"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": ["subtotal + gst == total"],
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-12": {
        "classification_hints": ["Employee expense", "Reimbursement"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": ["subtotal + gst == total"],
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
    "DT-26": {
        "classification_hints": ["Sales Invoice", "AR invoice"],
        "negative_hints": DEFAULT_NEGATIVE,
        "cross_field_rules": INVOICE_CROSS_RULES,
        "azure_di_profile": "prebuilt-invoice",
        "fallback_if_unknown_subtype": "generic_financial_document",
    },
}


def main() -> None:
    defaults_path = ROOT / "data" / "document_type_defaults.json"
    raw = json.loads(defaults_path.read_text(encoding="utf-8"))
    types_path = ROOT / "data" / "document_types.json"
    types = {row["code"].upper(): row for row in json.loads(types_path.read_text(encoding="utf-8"))}

    for code, row in raw.items():
        token = code.upper()
        meta = DT_META.get(token, {})
        short = str(types.get(token, {}).get("shortTitle") or types.get(token, {}).get("title") or "").strip()
        row.setdefault("classification_hints", meta.get("classification_hints") or ([short] if short else []))
        row.setdefault("negative_hints", meta.get("negative_hints", []))
        row.setdefault("cross_field_rules", meta.get("cross_field_rules", []))
        row.setdefault("field_overrides", meta.get("field_overrides", {}))
        row.setdefault("azure_di_profile", meta.get("azure_di_profile", ""))
        row.setdefault(
            "fallback_if_unknown_subtype",
            meta.get("fallback_if_unknown_subtype", "generic_financial_document"),
        )

    defaults_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"Updated {len(raw)} document type defaults")


if __name__ == "__main__":
    main()
