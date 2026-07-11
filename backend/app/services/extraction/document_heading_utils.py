"""Detect document titles/headings from OCR text for classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.schemas.document_type import DocumentTypeDefinition

HeadingKind = Literal[
    "tax_invoice",
    "commercial_invoice",
    "invoice",
    "purchase_order",
    "sales_order",
    "grn",
    "credit_note",
    "quote",
    "remittance",
    "proforma",
    "timesheet",
    "statement",
    "contract",
    "packing_list",
    "certificate_of_origin",
    "transport_doc",
    "customs_permit",
]

HeadingKindSource = Literal["title_line", "body_keyword"]


@dataclass(frozen=True)
class InferredPageHeading:
    kind: HeadingKind
    source: HeadingKindSource

_HEADING_SCAN_LINES = 30

_CONTINUATION_PAGE = re.compile(
    r"\b(?:continuation\s+page|\(continuation\s+page\)|\(cont(?:\.|inued)?\))\b",
    re.I,
)

# Keyword fallback when title is embedded in OCR layout (import / logistics dossiers).
_PAGE_KIND_KEYWORDS: list[tuple[re.Pattern[str], HeadingKind]] = [
    (re.compile(r"\bCOMMERCIAL\s+INVOICE\b", re.I), "commercial_invoice"),
    (re.compile(r"\bCARGO\s+CLEARANCE\s+PERMIT\b", re.I), "customs_permit"),
    (re.compile(r"\bCUSTOMS?\s+(?:ENTRY|DECLARATION)\b", re.I), "customs_permit"),
    (re.compile(r"\bPACKING\s+LIST\b", re.I), "packing_list"),
    (re.compile(r"\bCERTIFICATE\s+OF\s+ORIGIN\b", re.I), "certificate_of_origin"),
    (re.compile(r"\b(?:HAWB|MAWB|AWB)\b", re.I), "transport_doc"),
    (re.compile(r"\b(?:HOUSE|AIR)\s+WAYBILL\b", re.I), "transport_doc"),
    (re.compile(r"\bShipper'?s?\s+Name\s+and\s+Address\b", re.I), "transport_doc"),
    (re.compile(r"\bConsignee'?s?\s+Name\s+and\s+Address\b", re.I), "transport_doc"),
    (re.compile(r"\bBILL\s+OF\s+LADING\b", re.I), "transport_doc"),
    (re.compile(r"\b(?:B/L|BL)\s*NO\b", re.I), "transport_doc"),
    (re.compile(r"\bGOODS\s+RECEIPT\b", re.I), "grn"),
    (re.compile(r"\bG\.?\s*R\.?\s*N\.?\b", re.I), "grn"),
    (re.compile(r"\bDEBIT\s+NOTE\b", re.I), "credit_note"),
]

# Standalone title line (full line is essentially the document type label).
_STANDALONE_TITLE = re.compile(
    r"^(?:"
    r"tax\s+invoice|"
    r"commercial\s+invoice|"
    r"invoice|"
    r"purchase\s+order|"
    r"sales\s+order|"
    r"goods\s+receipt(?:\s+note)?|"
    r"g\.?\s*r\.?\s*n\.?|"
    r"delivery\s+(?:note|docket)|"
    r"credit\s+note|"
    r"debit\s+note|"
    r"quotation|quote|"
    r"remittance(?:\s+advice)?|"
    r"pro[\s-]?forma(?:\s+invoice)?|"
    r"timesheet|time\s+sheet|"
    r"statement\s+of\s+account|"
    r"vendor\s+statement|"
    r"contract|"
    r"agreement|"
    r"packing\s+list(?:\s*/\s*weight\s+list)?|"
    r"certificate\s+of\s+origin|"
    r"cargo\s+clearance\s+permit"
    r")\s*\.?$",
    re.I,
)

# Trailing title on a vendor/header line (e.g. "ACME PTY LTD TAX INVOICE").
_TRAILING_TITLE = re.compile(
    r"\b(?:"
    r"tax\s+invoice|"
    r"commercial\s+invoice|"
    r"invoice|"
    r"purchase\s+order|"
    r"sales\s+order|"
    r"goods\s+receipt(?:\s+note)?|"
    r"credit\s+note"
    r")\s*$",
    re.I,
)

_KIND_FROM_LABEL: list[tuple[re.Pattern[str], HeadingKind]] = [
    (re.compile(r"^tax\s+invoice$", re.I), "tax_invoice"),
    (re.compile(r"^commercial\s+invoice$", re.I), "commercial_invoice"),
    (re.compile(r"^invoice$", re.I), "invoice"),
    (re.compile(r"^purchase\s+order$", re.I), "purchase_order"),
    (re.compile(r"^sales\s+order$", re.I), "sales_order"),
    (re.compile(r"^goods\s+receipt", re.I), "grn"),
    (re.compile(r"^g\.?\s*r\.?\s*n\.?$", re.I), "grn"),
    (re.compile(r"^delivery\s+(?:note|docket)", re.I), "grn"),
    (re.compile(r"^credit\s+note$", re.I), "credit_note"),
    (re.compile(r"^debit\s+note$", re.I), "credit_note"),
    (re.compile(r"^(?:quotation|quote)$", re.I), "quote"),
    (re.compile(r"^remittance", re.I), "remittance"),
    (re.compile(r"^pro[\s-]?forma", re.I), "proforma"),
    (re.compile(r"^time\s*sheet|^timesheet", re.I), "timesheet"),
    (re.compile(r"^statement", re.I), "statement"),
    (re.compile(r"^contract|^agreement", re.I), "contract"),
    (re.compile(r"^packing\s+list", re.I), "packing_list"),
    (re.compile(r"^certificate\s+of\s+origin", re.I), "certificate_of_origin"),
    (re.compile(r"^cargo\s+clearance\s+permit", re.I), "customs_permit"),
]


@dataclass(frozen=True)
class DocumentHeadingSignals:
    primary_label: str | None
    primary_kind: HeadingKind | None
    kinds: tuple[HeadingKind, ...]

    @property
    def has_heading_invoice(self) -> bool:
        return (
            "invoice" in self.kinds
            or "tax_invoice" in self.kinds
            or "commercial_invoice" in self.kinds
        )

    @property
    def has_heading_po(self) -> bool:
        return "purchase_order" in self.kinds

    @property
    def has_heading_so(self) -> bool:
        return "sales_order" in self.kinds

    @property
    def has_heading_grn(self) -> bool:
        return "grn" in self.kinds

    @property
    def has_heading_credit_note(self) -> bool:
        return "credit_note" in self.kinds

    @property
    def has_heading_quote(self) -> bool:
        return "quote" in self.kinds

    @property
    def has_heading_contract(self) -> bool:
        return "contract" in self.kinds


def is_doc_title_line(line: str) -> bool:
    cleaned = line.strip()
    if not cleaned:
        return False
    if _STANDALONE_TITLE.match(cleaned):
        return True
    return bool(_TRAILING_TITLE.search(cleaned))


def strip_doc_title_from_line(line: str) -> str:
    return _TRAILING_TITLE.sub("", line.strip()).strip()


def _kind_for_label(label: str) -> HeadingKind | None:
    normalized = re.sub(r"\s+", " ", label.strip())
    for pattern, kind in _KIND_FROM_LABEL:
        if pattern.search(normalized):
            return kind
    return None


def _label_from_line(line: str) -> str | None:
    cleaned = line.strip()
    if not cleaned:
        return None
    if _STANDALONE_TITLE.match(cleaned):
        return re.sub(r"\s+", " ", cleaned).rstrip(".")
    trailing = _TRAILING_TITLE.search(cleaned)
    if trailing:
        return re.sub(r"\s+", " ", trailing.group(0).strip())
    if re.match(r"^(contract|agreement)\b", cleaned, re.I):
        return re.sub(r"\s+", " ", cleaned).rstrip(".")
    return None


def extract_document_heading_signals(text: str) -> DocumentHeadingSignals:
    """Scan the top of OCR text for document-type headings."""
    return _heading_signals_from_lines(text, include_body_fallback=True)


def _heading_signals_from_lines(
    text: str,
    *,
    include_body_fallback: bool = True,
) -> DocumentHeadingSignals:
    if not text or not text.strip():
        return DocumentHeadingSignals(primary_label=None, primary_kind=None, kinds=())

    kinds: list[HeadingKind] = []
    labels: list[str] = []
    seen_kinds: set[HeadingKind] = set()

    for raw_line in text.splitlines()[:_HEADING_SCAN_LINES]:
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        label = _label_from_line(line)
        if not label:
            continue
        kind = _kind_for_label(label)
        if kind is None:
            continue
        labels.append(label)
        if kind not in seen_kinds:
            seen_kinds.add(kind)
            kinds.append(kind)

    if include_body_fallback and not kinds:
        blob = "\n".join(text.splitlines()[:50])
        for pattern, kind in _PAGE_KIND_KEYWORDS:
            if kind in seen_kinds:
                continue
            if pattern.search(blob):
                seen_kinds.add(kind)
                kinds.append(kind)
                labels.append(kind.replace("_", " "))

    primary_label = labels[0] if labels else None
    primary_kind = kinds[0] if kinds else None
    return DocumentHeadingSignals(
        primary_label=primary_label,
        primary_kind=primary_kind,
        kinds=tuple(kinds),
    )


def is_continuation_page(text: str) -> bool:
    """True when OCR indicates this page continues the previous document."""
    return bool(_CONTINUATION_PAGE.search(text or ""))


def infer_page_document_kind_with_source(text: str) -> InferredPageHeading | None:
    """Detect page kind and whether it came from a title line vs body keywords."""
    if not text or not text.strip():
        return None
    if is_continuation_page(text):
        return None

    title_signals = _heading_signals_from_lines(text, include_body_fallback=False)
    if title_signals.primary_kind is not None:
        return InferredPageHeading(kind=title_signals.primary_kind, source="title_line")

    blob = "\n".join(text.splitlines()[:50])
    for pattern, kind in _PAGE_KIND_KEYWORDS:
        if pattern.search(blob):
            return InferredPageHeading(kind=kind, source="body_keyword")
    return None


def infer_page_document_kind(text: str) -> HeadingKind | None:
    """Detect document kind from a single page (headings + import/logistics keywords)."""
    inferred = infer_page_document_kind_with_source(text)
    return inferred.kind if inferred else None


def _expected_heading_kinds(
    definition: DocumentTypeDefinition | None,
) -> frozenset[HeadingKind] | None:
    """Infer expected OCR headings from org-defined card metadata — not DT code."""
    if definition is None:
        return None
    role = (definition.purchase_bundle_role or "").strip().lower()
    if role == "po":
        return frozenset({"purchase_order"})
    if role == "grn":
        return frozenset({"grn"})
    profile = (definition.playbook_profile or "").strip().lower()
    if profile == "reconciliation":
        return frozenset({"statement"})
    if profile in {"informational", "master_data"}:
        return frozenset({"statement", "remittance", "quote", "contract"})
    from app.services.classification.document_type_klass import is_trans_posting

    if not is_trans_posting(definition):
        return None
    return frozenset({"invoice", "tax_invoice", "credit_note", "proforma"})


_HEADING_KIND_TOKENS: dict[str, tuple[str, ...]] = {
    "commercial_invoice": ("commercial invoice", "commercial inv"),
    "tax_invoice": ("tax invoice",),
    "invoice": ("invoice",),
    "packing_list": ("packing list", "weight list", "packing"),
    "certificate_of_origin": ("certificate of origin", "origin certificate", "coo"),
    "transport_doc": ("hawb", "mawb", "air waybill", "bill of lading", "awb", "b/l"),
    "customs_permit": (
        "cargo clearance permit",
        "customs permit",
        "customs entry",
        "import declaration",
        "clearance permit",
    ),
    "purchase_order": ("purchase order", " po "),
    "grn": ("goods receipt", "grn", "delivery note", "delivery docket"),
    "credit_note": ("credit note", "debit note"),
    "quote": ("quotation", "quote", "estimate"),
    "contract": ("contract", "sow", "statement of work", "rate card", "agreement"),
    "statement": ("statement of account", "vendor statement"),
    "remittance": ("remittance",),
    "proforma": ("pro forma", "proforma"),
    "timesheet": ("timesheet", "time sheet"),
}


def _definition_metadata_blob(definition: DocumentTypeDefinition) -> str:
    parts = [
        definition.short_title or "",
        definition.title or "",
        definition.llm_prompt or "",
        " ".join(definition.extraction or []),
    ]
    return " ".join(parts).lower()


def _classifier_document_text_blob(definition: DocumentTypeDefinition) -> str:
    chunks: list[str] = []

    def walk(node: dict | None) -> None:
        if not node:
            return
        if node.get("type") == "condition" and node.get("field") == "document_text":
            value = node.get("value")
            if isinstance(value, str) and value.strip():
                chunks.append(value.lower())
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(definition.classifier.root)
    return " ".join(chunks)


def _token_matches_blob(token: str, blob: str) -> bool:
    """Substring match for long phrases; word-boundary for short tokens."""
    if not token or not blob:
        return False
    if len(token) <= 4 or token in {"b/l", " po ", "awb", "hawb", "mawb", "grn", "coo", "sow"}:
        pattern = rf"(?<![\w/]){re.escape(token.strip())}(?![\w/])"
        return bool(re.search(pattern, blob, flags=re.I))
    return token in blob


def score_document_type_for_heading(
    definition: DocumentTypeDefinition,
    heading_kind: HeadingKind,
) -> float:
    tokens = _HEADING_KIND_TOKENS.get(heading_kind, ())
    if not tokens or not definition.enabled:
        return 0.0

    metadata = _definition_metadata_blob(definition)
    classifier_text = _classifier_document_text_blob(definition)
    short_title = (definition.short_title or "").lower()
    best = 0.0

    for token in tokens:
        token = token.strip().lower()
        if not token:
            continue
        if _token_matches_blob(token, short_title):
            best = max(best, 1.0)
            continue
        if _token_matches_blob(token, metadata):
            best = max(best, 0.82)
        if _token_matches_blob(token, classifier_text):
            best = max(best, 0.88)
        for part in re.split(r"[\s/·]+", metadata):
            if part and token == part:
                best = max(best, 0.95)
    return best


def heading_alignment_score(
    document_type_code: str,
    signals: DocumentHeadingSignals,
    *,
    document_text: str = "",
    definition: DocumentTypeDefinition | None = None,
) -> float:
    """
    0–1 score: how well the detected page heading agrees with the document type.
    Uses org card metadata when available; neutral when unknown.
    """
    _ = document_type_code
    body = (document_text or "").lower()

    kind = signals.primary_kind
    if kind is None and document_text.strip():
        kind = infer_page_document_kind(document_text)

    if kind is None:
        return 0.55

    if definition is not None:
        metadata_score = score_document_type_for_heading(definition, kind)
        if metadata_score > 0:
            return metadata_score

    expected = _expected_heading_kinds(definition)
    if expected is None:
        return 0.55

    if kind in expected:
        return 1.0

    role = (definition.purchase_bundle_role or "").strip().lower() if definition else ""
    if role == "po" and signals.has_heading_invoice:
        return 0.35
    if role == "grn" and signals.has_heading_invoice:
        return 0.35

    if frozenset({"invoice", "tax_invoice"}) & expected and kind == "purchase_order":
        return 0.25

    if frozenset({"contract"}) & expected and signals.has_heading_invoice:
        if "terms and conditions" in body or "governing law" in body:
            return 0.2
        return 0.45

    return 0.4
