"""Flag-aware facade over field registry and legacy Python constants."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.registry.field_definition import FieldDefinition, JurisdictionFieldVariant
from app.registry.loader import get_field_registry
from app.services.classification.document_type_field_keys import (
    CANONICAL_EXTRACTION_FIELD_KEYS,
    POSTING_CRITICAL_FIELD_KEYS,
)


def use_field_registry() -> bool:
    return bool(get_settings().use_field_registry)


def _legacy_hint(key: str) -> str:
    from app.services.extraction.extraction_field_values import (
        _FIELD_HINT_PATTERNS,
        extraction_field_label,
    )

    if key in _FIELD_HINT_PATTERNS:
        return _FIELD_HINT_PATTERNS[key]
    return f'label "{extraction_field_label(key)}" or similar heading in OCR'


def _legacy_finance_role(key: str) -> tuple[str, tuple[str, ...]]:
    from app.services.extraction.extraction_field_values import _FINANCE_FIELD_DEFS

    row = _FINANCE_FIELD_DEFS.get(key, {})
    role = str(row.get("finance_role") or "").strip()
    confuse_raw = str(row.get("do_not_use") or "").strip()
    confuse: list[str] = []
    if confuse_raw:
        for part in confuse_raw.split(","):
            token = part.strip().lower().replace(" ", "_")
            if token in CANONICAL_EXTRACTION_FIELD_KEYS:
                confuse.append(token)
            elif "buyer" in part.lower():
                confuse.append("buyer_name")
            elif "invoice" in part.lower() and "number" in part.lower():
                confuse.append("invoice_no")
            elif "po" in part.lower():
                confuse.append("po_reference")
    return role, tuple(confuse)


def _legacy_data_type(key: str) -> str:
    if key in {"subtotal", "gst", "gst_rate", "total"}:
        return "money"
    if key in {"invoice_date", "due_date"}:
        return "date"
    if key == "line_items":
        return "line_items"
    if key in {"bank_details", "bank_bsb", "bank_account", "bank_name"}:
        return "bank"
    if key in {"document_text", "attachment_name", "document_heading", "email_subject"}:
        return "text"
    return "string"


def _legacy_grounding_required(key: str) -> bool:
    if key in {"attachment_name", "document_text", "email_subject"}:
        return False
    if key == "line_items":
        return True
    return True


def _legacy_source_priority(key: str) -> tuple[str, ...]:
    if key == "total":
        return ("azure_di", "llm", "regex")
    if key == "vendor":
        return ("llm", "layout_kv", "azure_di")
    return ("llm", "azure_di", "layout_kv", "regex")


def _tax_id_jurisdiction_variants() -> dict[str, JurisdictionFieldVariant]:
    return {
        "AU": JurisdictionFieldVariant(name="ABN", regex=r"^\d{11}$", checksum="abn_checksum"),
        "IN": JurisdictionFieldVariant(
            name="GSTIN",
            regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
        ),
        "SG": JurisdictionFieldVariant(
            name="UEN",
            regex=r"^[0-9]{8,10}[A-Z]$|^[ST]\d{2}[A-Z]{2}\d{4}[A-Z]$",
        ),
        "GB": JurisdictionFieldVariant(name="VAT Number", regex=r"^[A-Z]{2}\d{8,12}$"),
        "EU": JurisdictionFieldVariant(name="VAT Number", regex=r"^[A-Z]{2}\d{8,12}$"),
        "DEFAULT": JurisdictionFieldVariant(name="Tax ID"),
    }


def _legacy_field_def(key: str) -> FieldDefinition | None:
    from app.services.extraction.extraction_field_values import extraction_field_label

    token = str(key or "").strip().lower()
    if not token or token not in CANONICAL_EXTRACTION_FIELD_KEYS:
        return None
    hint = _legacy_hint(token)
    synonyms = tuple(part.strip() for part in hint.split(",") if part.strip())
    finance_role, confuse = _legacy_finance_role(token)
    tax_keys = {"abn", "seller_abn", "buyer_abn", "seller_tax_id", "buyer_tax_id"}
    return FieldDefinition(
        key=token,
        label=extraction_field_label(token),
        data_type=_legacy_data_type(token),
        category="party_identifier" if token in tax_keys else "general",
        posting_critical=token in POSTING_CRITICAL_FIELD_KEYS,
        grounding_required=_legacy_grounding_required(token),
        synonyms=synonyms,
        extraction_hint=hint,
        finance_role=finance_role,
        do_not_confuse_with=confuse,
        jurisdiction_variants=_tax_id_jurisdiction_variants() if token in tax_keys else {},
        source_priority=_legacy_source_priority(token),
    )


class RegistryAdapter:
    """Single entry point for field metadata."""

    def field_def(self, key: str) -> FieldDefinition | None:
        token = str(key or "").strip().lower()
        if not token:
            return None
        if use_field_registry():
            return get_field_registry().fields.get(token)
        return _legacy_field_def(token)

    def posting_critical_keys(self) -> frozenset[str]:
        if use_field_registry():
            return frozenset(
                key for key, row in get_field_registry().fields.items() if row.posting_critical
            )
        return POSTING_CRITICAL_FIELD_KEYS

    def synonyms_for(self, key: str, *, locale: str = "en") -> list[str]:
        del locale
        row = self.field_def(key)
        if row is None:
            return []
        return list(row.synonyms)

    def hint_for(self, key: str) -> str:
        row = self.field_def(key)
        if row is None:
            return _legacy_hint(key)
        if row.extraction_hint:
            return row.extraction_hint
        if row.synonyms:
            return ", ".join(row.synonyms)
        return row.label

    def do_not_confuse_pairs(self, keys: list[str] | None = None) -> list[tuple[str, str]]:
        selected = {str(k).strip().lower() for k in (keys or []) if str(k).strip()}
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        registry = get_field_registry().fields if use_field_registry() else {}
        source_keys = selected or set(registry.keys()) or CANONICAL_EXTRACTION_FIELD_KEYS
        for key in source_keys:
            row = self.field_def(key)
            if row is None:
                continue
            for other in row.do_not_confuse_with:
                pair = (key, other)
                rev = (other, key)
                if pair in seen or rev in seen:
                    continue
                seen.add(pair)
                pairs.append(pair)
        return pairs

    def jurisdiction_variant(self, key: str, country: str) -> JurisdictionFieldVariant:
        row = self.field_def(key)
        if row is None or not row.jurisdiction_variants:
            return JurisdictionFieldVariant(name="Tax ID")
        token = str(country or "").strip().upper()
        if token in row.jurisdiction_variants:
            return row.jurisdiction_variants[token]
        return row.jurisdiction_variants.get("DEFAULT", JurisdictionFieldVariant(name="Tax ID"))

    def grounding_required(self, key: str) -> bool:
        row = self.field_def(key)
        if row is None:
            return _legacy_grounding_required(key)
        return row.grounding_required

    def manifest_for_keys(self, keys: list[str], *, country: str = "") -> list[dict[str, str]]:
        del country
        from app.services.classification.document_type_field_keys import is_valid_extraction_field_key

        seen: set[str] = set()
        manifest: list[dict[str, str]] = []
        for raw in keys:
            token = str(raw or "").strip().lower()
            if not token or token in seen or not is_valid_extraction_field_key(token):
                continue
            seen.add(token)
            if token in {"attachment_name", "document_text"}:
                continue
            row = self.field_def(token)
            manifest.append(
                {
                    "key": token,
                    "label": row.label if row else token.replace("_", " ").title(),
                    "hint": self.hint_for(token),
                }
            )
        return manifest

    def finance_defs_for_keys(self, keys: list[str]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for raw in keys:
            token = str(raw or "").strip().lower()
            row = self.field_def(token)
            if row is None or not row.finance_role:
                continue
            out.append(
                {
                    "key": token,
                    "finance_role": row.finance_role,
                    "do_not_use": ", ".join(row.do_not_confuse_with),
                    "deprioritized_labels": list(row.deprioritized_label_qualifiers),
                }
            )
        return out

    def accuracy_prompt_lines(self) -> list[str]:
        lines = [
            "",
            "Accuracy rules (mandatory):",
            "- Copy values verbatim from OCR only; empty is correct when a field is absent — never invent to satisfy the manifest.",
            "- If a value is not explicitly printed in ocr.text_excerpt or field_snippets, leave the field empty.",
            "- Never default currency (e.g. AUD), assume tax rates, or calculate totals from other fields.",
        ]
        for left, right in self.do_not_confuse_pairs():
            lines.append(f"- Never swap semantically similar fields ({left} ≠ {right}).")
        lines.extend(
            [
                "- invoice_no: copy ONLY the invoice/reference token — never include trailing DATED/DATE labels or dates in invoice_no; put dates in invoice_date.",
                "- field_confidence: 0.0 when empty; 0.95+ only for verbatim OCR copies.",
                "- field_citations: for every non-empty field, copy the exact OCR snippet where the value appears; empty snippet when field is empty.",
                "- Example: if you see 'Tax Invoice' but no invoice number label, invoice_no stays empty.",
                "- Example: if project_code is not labeled in OCR, do not infer it from PO or line items.",
            ]
        )
        return lines

    def source_priority_for(self, key: str) -> tuple[str, ...]:
        row = self.field_def(key)
        if row is None:
            return _legacy_source_priority(key)
        return row.source_priority


@lru_cache
def get_registry_adapter() -> RegistryAdapter:
    return RegistryAdapter()
