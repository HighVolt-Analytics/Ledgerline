"""Tests for document heading extraction and alignment scoring."""

from app.services.extraction.document_heading_utils import (
    extract_document_heading_signals,
    heading_alignment_score,
    is_doc_title_line,
    strip_doc_title_from_line,
)


def test_extract_standalone_tax_invoice_heading() -> None:
    text = "ACME PTY LTD\nTAX INVOICE\nInvoice No: INV-1\nTotal $100"
    signals = extract_document_heading_signals(text)
    assert signals.primary_label == "TAX INVOICE"
    assert signals.primary_kind == "tax_invoice"
    assert signals.has_heading_invoice is True


def test_extract_purchase_order_heading() -> None:
    text = "PURCHASE ORDER\nPO Number: 12345"
    signals = extract_document_heading_signals(text)
    assert signals.has_heading_po is True
    assert signals.primary_kind == "purchase_order"


def test_trailing_title_on_vendor_line() -> None:
    line = "AFMA PTY LTD TAX INVOICE"
    assert is_doc_title_line(line) is True
    assert strip_doc_title_from_line(line) == "AFMA PTY LTD"


def test_heading_alignment_grn_dt03() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    signals = extract_document_heading_signals("GOODS RECEIPT NOTE\nPO 12345")
    definition = DocumentTypeDefinition(
        code="DT-03",
        title="GRN",
        shortTitle="GRN",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_grn"], llm_prompt="",
        routeTarget="Purchase Management",
        purchaseBundleRole="grn",
    )
    score = heading_alignment_score("DT-03", signals, document_text="GOODS RECEIPT NOTE", definition=definition)
    assert score == 1.0


def test_heading_alignment_contract_penalises_invoice_header() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    body = "TAX INVOICE\nterms and conditions\ngoverning law"
    signals = extract_document_heading_signals(body)
    definition = DocumentTypeDefinition(
        code="DT-16",
        title="Contract",
        shortTitle="Contract",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals", recognition_signals=["heading_contract"], llm_prompt="",
        routeTarget="Vault",
        playbook_profile="master_data",
    )
    score = heading_alignment_score("DT-16", signals, document_text=body, definition=definition)
    assert score == 0.2


def test_heading_alignment_neutral_when_no_heading() -> None:
    signals = extract_document_heading_signals("Random vendor letter\nNo title here")
    score = heading_alignment_score("DT-03", signals)
    assert score == 0.55


def test_heading_alignment_cargo_clearance_permit_dt03() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    text = "CARGO CLEARANCE PERMIT\nPermit No: ABC-123\nImporter details"
    signals = extract_document_heading_signals(text)
    definition = DocumentTypeDefinition(
        code="DT-03",
        title="Cargo Clearance Permit",
        shortTitle="Cargo Clearance Permit",
        klass="Non-transactional",
        posting="No",
        recognition_mode="prompt", recognition_signals=[], llm_prompt="Import customs clearance permit",
        routeTarget="Purchase Management",
        playbook_profile="import_dossier",
    )
    score = heading_alignment_score("DT-03", signals, document_text=text, definition=definition)
    assert score >= 0.82


def test_infer_import_logistics_page_kinds() -> None:
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    assert infer_page_document_kind("COMMERCIAL INVOICE\nInv 1") == "commercial_invoice"
    assert infer_page_document_kind("PACKING LIST / WEIGHT LIST") == "packing_list"
    assert infer_page_document_kind("CERTIFICATE OF ORIGIN") == "certificate_of_origin"
    assert infer_page_document_kind("HAWB NO: ABC123") == "transport_doc"
    assert infer_page_document_kind("CARGO CLEARANCE PERMIT\nPERMIT 1") == "customs_permit"
    assert infer_page_document_kind("(CONTINUATION PAGE)\nMore lines") is None


def test_extract_abbreviated_grn_heading() -> None:
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    assert infer_page_document_kind("GRN\nPO 9001") == "grn"
    assert infer_page_document_kind("G.R.N.\nReceived qty 5") == "grn"


def test_extract_debit_note_heading() -> None:
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    assert infer_page_document_kind("DEBIT NOTE\nRef DN-1") == "credit_note"
