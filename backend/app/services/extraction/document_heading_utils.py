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
# Seagate / SAP style: "Page : 2 of 3", "Page 2/3", "Page 2 of 3"
_PAGE_OF_MARKER = re.compile(
    r"\bpage\s*:?\s*(\d+)\s*(?:of|/)\s*(\d+)\b",
    re.I,
)

# Keyword fallback when title is embedded in OCR layout (import / logistics dossiers).
# Prefer commercial titles over logistics *field labels* (e.g. "Bill of Lading No" on an invoice).
_PAGE_KIND_KEYWORDS: list[tuple[re.Pattern[str], HeadingKind]] = [
    (re.compile(r"\bTAX\s+INVOICE\b", re.I), "tax_invoice"),
    (re.compile(r"\bCOMMERCIAL\s+INVOICE\b", re.I), "commercial_invoice"),
    (re.compile(r"\bPRO[\s-]?FORMA(?:\s+INVOICE)?\b", re.I), "proforma"),
    (re.compile(r"\bINVOICE\b", re.I), "invoice"),
    (re.compile(r"\bCARGO\s+CLEARANCE\s+PERMIT\b", re.I), "customs_permit"),
    (re.compile(r"\bCUSTOMS?\s+(?:ENTRY|DECLARATION)\b", re.I), "customs_permit"),
    # Avoid field labels like "Packing List No:" on invoices (same idea as Invoice No).
    (re.compile(r"\bPACKING\s+LIST\b(?!\s*no\b)", re.I), "packing_list"),
    (re.compile(r"\bCERTIFICATE\s+OF\s+ORIGIN\b", re.I), "certificate_of_origin"),
    (re.compile(r"\bBENEFICIARY\s+SHIPMENT\s+ADVICE\b", re.I), "statement"),
    (re.compile(r"\bSHIPMENT\s+ADVICE\b", re.I), "statement"),
    (re.compile(r"\b(?:HAWB|MAWB|AWB)\s*NO\.?\b", re.I), "transport_doc"),
    (re.compile(r"\b(?:HOUSE|AIR)\s+WAYBILL\b", re.I), "transport_doc"),
    (re.compile(r"\bAIR\s+FREIGHT\s+SERVICES\b", re.I), "transport_doc"),
    (re.compile(r"\bNot\s+Negotiable\s+Air\s+Waybill\b", re.I), "transport_doc"),
    (re.compile(r"\bShipper'?s?\s+Name\s+and\s+Address\b", re.I), "transport_doc"),
    (re.compile(r"\bConsignee'?s?\s+Name\s+and\s+Address\b", re.I), "transport_doc"),
    # Title "BILL OF LADING" only — not the common invoice/packing field "Bill of Lading No".
    (re.compile(r"\bBILL\s+OF\s+LADING\b(?!\s*NO\b)", re.I), "transport_doc"),
    (re.compile(r"\bGOODS\s+RECEIPT\b", re.I), "grn"),
    (re.compile(r"\bG\.?\s*R\.?\s*N\.?\b", re.I), "grn"),
    (re.compile(r"\bPROOF\s+OF\s+DELIVERY\b", re.I), "grn"),
    (re.compile(r"\bPOD\b", re.I), "grn"),
    (re.compile(r"\bDELIVERY\s+(?:NOTE|RECEIPT|DOCKET)\b", re.I), "grn"),
    (re.compile(r"\bDEBIT\s+NOTE\b", re.I), "credit_note"),
]

# Title/body kinds that beat logistics field labels when both appear on one page.
_STRONG_PAGE_KINDS: frozenset[HeadingKind] = frozenset(
    {
        "tax_invoice",
        "commercial_invoice",
        "invoice",
        "proforma",
        "packing_list",
        "purchase_order",
        "sales_order",
        "grn",
        "credit_note",
        "customs_permit",
        "certificate_of_origin",
        "statement",
        "remittance",
        "quote",
        "contract",
        "timesheet",
    }
)

# Standalone title line (full line is essentially the document type label).
_STANDALONE_TITLE = re.compile(
    r"^(?:"
    r"tax\s+invoice|"
    r"commercial\s+invoice|"
    # "INVOICE 9300667281" / "INVOICE COMPUTER GENERATED DOCUMENT" — not "Invoice No:"
    r"invoice(?!\s*no\b)(?:\s+\S+)*|"
    r"purchase\s+order|"
    r"sales\s+order|"
    r"goods\s+receipt(?:\s+note)?|"
    r"g\.?\s*r\.?\s*n\.?|"
    r"delivery\s+(?:note|receipt|docket)|"
    r"proof\s+of\s+delivery|"
    r"pod|"
    r"credit\s+note|"
    r"debit\s+note|"
    r"quotation|quote|"
    r"remittance(?:\s+advice)?|"
    r"pro[\s-]?forma(?:\s+invoice)?|"
    r"timesheet|time\s+sheet|"
    r"statement\s+of\s+account|"
    r"vendor\s+statement|"
    r"beneficiary\s+shipment\s+advice|"
    r"shipment\s+advice|"
    r"contract|"
    r"agreement|"
    r"packing\s+list(?:\s*/\s*weight\s+list)?|"
    r"certificate\s+of\s+origin|"
    r"cargo\s+clearance\s+permit|"
    r"air\s+freight\s+services|"
    r"(?:house|air)\s+waybill|"
    r"bill\s+of\s+lading"
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
    (re.compile(r"^invoice(?!\s*no\b)", re.I), "invoice"),
    (re.compile(r"^purchase\s+order$", re.I), "purchase_order"),
    (re.compile(r"^sales\s+order$", re.I), "sales_order"),
    (re.compile(r"^goods\s+receipt", re.I), "grn"),
    (re.compile(r"^g\.?\s*r\.?\s*n\.?$", re.I), "grn"),
    (re.compile(r"^delivery\s+(?:note|receipt|docket)", re.I), "grn"),
    (re.compile(r"^proof\s+of\s+delivery$", re.I), "grn"),
    (re.compile(r"^pod$", re.I), "grn"),
    (re.compile(r"^credit\s+note$", re.I), "credit_note"),
    (re.compile(r"^debit\s+note$", re.I), "credit_note"),
    (re.compile(r"^(?:quotation|quote)$", re.I), "quote"),
    (re.compile(r"^remittance", re.I), "remittance"),
    (re.compile(r"^pro[\s-]?forma", re.I), "proforma"),
    (re.compile(r"^time\s*sheet|^timesheet", re.I), "timesheet"),
    (re.compile(r"^beneficiary\s+shipment\s+advice", re.I), "statement"),
    (re.compile(r"^shipment\s+advice", re.I), "statement"),
    (re.compile(r"^statement", re.I), "statement"),
    (re.compile(r"^contract|^agreement", re.I), "contract"),
    (re.compile(r"^packing\s+list", re.I), "packing_list"),
    (re.compile(r"^certificate\s+of\s+origin", re.I), "certificate_of_origin"),
    (re.compile(r"^cargo\s+clearance\s+permit", re.I), "customs_permit"),
    (re.compile(r"^air\s+freight\s+services", re.I), "transport_doc"),
    (re.compile(r"^(?:house|air)\s+waybill", re.I), "transport_doc"),
    (re.compile(r"^bill\s+of\s+lading", re.I), "transport_doc"),
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


def heading_kind_for_label(label: str) -> HeadingKind | None:
    """Map a vault / heading display label to a coarse document kind."""
    return _kind_for_label(label)


_INVOICE_FAMILY_KINDS: frozenset[HeadingKind] = frozenset(
    {
        "tax_invoice",
        "commercial_invoice",
        "invoice",
        "credit_note",
    }
)

# Customer / sales / vendor invoices that do not start with "Invoice".
_INVOICE_FAMILY_LABEL_RE = re.compile(
    r"(?:"
    r"\b(?:customer|sales|vendor|tax|commercial)\s+invoice\b"
    r"|\binvoice\b(?!\s*no\b)"
    r"|\b(?:credit|debit)\s+note\b"
    r")",
    re.I,
)

_PROFORMA_LABEL_RE = re.compile(r"\bpro[\s-]?forma\b", re.I)


def is_invoice_family_vault_label(label: str | None) -> bool:
    """True when a vault type folder / vision label is an invoice-family anchor.

    Includes tax / commercial / customer / sales invoices and credit/debit notes.
    Excludes packing lists, transport docs, PO/SO/GRN, remittance, proforma, etc.
    """
    raw = (label or "").strip()
    if not raw:
        return False
    if _PROFORMA_LABEL_RE.search(raw):
        return False
    kind = _kind_for_label(raw)
    if kind is not None:
        return kind in _INVOICE_FAMILY_KINDS
    return bool(_INVOICE_FAMILY_LABEL_RE.search(raw))


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
        layout_kind = _layout_kind_from_cues(text)
        if layout_kind is not None:
            kinds.append(layout_kind)
            labels.append(layout_kind.replace("_", " "))
        else:
            preferred = _pick_preferred_body_kind(_body_keyword_kinds(text))
            if preferred is not None:
                kinds.append(preferred)
                labels.append(preferred.replace("_", " "))

    primary_label = labels[0] if labels else None
    primary_kind = kinds[0] if kinds else None
    return DocumentHeadingSignals(
        primary_label=primary_label,
        primary_kind=primary_kind,
        kinds=tuple(kinds),
    )


def parse_page_of_marker(text: str) -> tuple[int, int] | None:
    """Return (current, total) for 'Page X of Y' markers, else None."""
    match = _PAGE_OF_MARKER.search(text or "")
    if not match:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    if current < 1 or total < 1 or current > total:
        return None
    return current, total


def is_continuation_page(text: str) -> bool:
    """True when OCR indicates this page continues the previous document.

    Includes explicit continuation labels and mid-run 'Page X of Y' (X > 1)
    for every document type (invoice, packing list, AWB, GRN/PoD, etc.).
    """
    raw = text or ""
    if _CONTINUATION_PAGE.search(raw):
        return True
    page_of = parse_page_of_marker(raw)
    return bool(page_of and page_of[0] > 1)


def _body_keyword_kinds(text: str) -> list[HeadingKind]:
    blob = "\n".join((text or "").splitlines()[:50])
    found: list[HeadingKind] = []
    seen: set[HeadingKind] = set()
    for pattern, kind in _PAGE_KIND_KEYWORDS:
        if kind in seen:
            continue
        if pattern.search(blob):
            found.append(kind)
            seen.add(kind)
    return found


# Seagate/SAP page-1 often omits the word INVOICE / PACKING LIST (title only on page 2).
_INVOICE_LAYOUT_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bUNIT\s+PRICE\b", re.I),
    re.compile(r"\bTOTAL\s+PRICE\b", re.I),
    re.compile(r"\bMATERIAL\s+NUMBER\b", re.I),
    re.compile(r"\bSHIPPING\s+ORGANIZATION\b", re.I),
    re.compile(r"\bSELLING\s+ORGANIZATION\b", re.I),
    re.compile(r"\bCOO\s*/\s*QTY\b", re.I),
)
_PACKING_LAYOUT_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bTOP\s+LEVEL\s+HANDLING\s+UNIT\b", re.I),
    re.compile(r"\bNUMBER\s+OF\s+CARTONS\b", re.I),
    re.compile(r"\bPACKAGE\s+TYPE\b", re.I),
)
_TRANSPORT_LAYOUT_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:HAWB|MAWB|AWB)\s*NO\.?\b", re.I),
    re.compile(r"\b(?:HOUSE|AIR)\s+WAYBILL\b", re.I),
    re.compile(r"\bAIR\s+FREIGHT\s+SERVICES\b", re.I),
    re.compile(r"\bNot\s+Negotiable\s+Air\s+Waybill\b", re.I),
    re.compile(r"\bShipper'?s?\s+Name\s+and\s+Address\b", re.I),
)


def _layout_kind_from_cues(text: str) -> HeadingKind | None:
    """Infer kind from commercial layout when the title word is missing on page 1."""
    blob = text or ""
    if any(p.search(blob) for p in _TRANSPORT_LAYOUT_CUES):
        return None
    packing_hits = sum(1 for p in _PACKING_LAYOUT_CUES if p.search(blob))
    if packing_hits >= 1:
        return "packing_list"
    invoice_hits = sum(1 for p in _INVOICE_LAYOUT_CUES if p.search(blob))
    if invoice_hits >= 2:
        return "invoice"
    return None


def _pick_preferred_body_kind(kinds: list[HeadingKind]) -> HeadingKind | None:
    if not kinds:
        return None
    strong = [kind for kind in kinds if kind in _STRONG_PAGE_KINDS]
    if strong:
        # Keep keyword-list order among strong kinds (invoice before packing, etc.).
        return strong[0]
    return kinds[0]


def infer_page_document_kind_with_source(text: str) -> InferredPageHeading | None:
    """Detect page kind and whether it came from a title line vs body keywords."""
    if not text or not text.strip():
        return None
    if is_continuation_page(text):
        return None

    title_signals = _heading_signals_from_lines(text, include_body_fallback=False)
    if title_signals.primary_kind is not None:
        return InferredPageHeading(kind=title_signals.primary_kind, source="title_line")

    # Prefer commercial layout over logistics *field labels* (BOL No on an invoice page).
    layout_kind = _layout_kind_from_cues(text)
    if layout_kind is not None:
        return InferredPageHeading(kind=layout_kind, source="body_keyword")

    body_kind = _pick_preferred_body_kind(_body_keyword_kinds(text))
    if body_kind is not None:
        return InferredPageHeading(kind=body_kind, source="body_keyword")
    return None


def infer_page_document_kind(text: str) -> HeadingKind | None:
    """Detect document kind from a single page (headings + import/logistics keywords)."""
    inferred = infer_page_document_kind_with_source(text)
    return inferred.kind if inferred else None


def document_role_from_heading(kind: HeadingKind | str | None) -> str | None:
    """Stable dedup role for a heading kind (invoice family collapses; supports stay distinct).

    Shipment packs often share invoice/PO numbers across Tax Invoice, Packing List,
    Delivery Note, AWB, etc. Dedup must not collapse those into one instrument.
    """
    token = (kind or "").strip().lower()
    if not token:
        return None
    if token in {"invoice", "tax_invoice", "commercial_invoice", "proforma", "credit_note"}:
        return "invoice"
    if token == "purchase_order":
        return "purchase_order"
    if token == "sales_order":
        return "sales_order"
    if token == "grn":
        return "grn"
    if token == "packing_list":
        return "packing_list"
    if token == "transport_doc":
        return "transport_doc"
    if token == "customs_permit":
        return "customs_permit"
    if token == "certificate_of_origin":
        return "certificate_of_origin"
    if token in {"quote", "remittance", "statement", "contract", "timesheet"}:
        return token
    return token


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


def score_document_type_for_heading(
    definition: DocumentTypeDefinition,
    heading_kind: HeadingKind,
) -> float:
    """Delegate to recognition-aware heading scoring (signals / prompt / title fallback)."""
    from app.services.classification.segment_heading_classification import (
        score_document_type_for_heading as _score,
    )

    return _score(definition, heading_kind)


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
