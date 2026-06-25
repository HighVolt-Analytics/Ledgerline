"""Catalogue preview uses the proposed classifier on the draft type."""

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import DocumentTypeSampleProposal
from app.services.document_classifier_builder import build_classifier_from_signals
from app.services.document_type_classify_preview import (
    classify_parsed_sample_against_catalog,
    classify_parsed_sample_for_proposal_preview,
    merge_draft_document_type,
    proposed_classifier_matches_sample,
)
from app.services.document_type_sample_analyzer import (
    ParsedDocumentSample,
    apply_sample_proposal_to_draft,
)
from app.services.invoice_data import InvoiceData


def _draft_contract_type() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-99",
        title="AFMA contract",
        shortTitle="AFMA contract",
        klass="Supporting",
        posting="No",
        fraudRisk="low",
        oneLine="AFMA forward contracts",
        routeTarget="Vault",
        classifier=DocumentTypeClassifier(enabled=False, priority=5, confidence=0.85),
    )


def test_apply_proposal_enables_classifier_and_routes_to_draft() -> None:
    from datetime import date
    from decimal import Decimal
    from app.models.invoice import InvoiceStatus

    proposal = DocumentTypeSampleProposal(
        recognition_signals=[
            "filename_contract",
            "heading_contract",
            "text_contract",
            "text_governing_law",
            "text_terms",
        ],
        classifier_layout="supporting_doc",
        playbook_profile="supporting",
        min_route_confidence=0.55,
    )
    draft = _draft_contract_type()
    proposed = apply_sample_proposal_to_draft(draft, proposal)
    assert proposed.classifier.enabled is True
    assert proposed.classifier.root["operator"] == "AND"

    parsed = InvoiceData(
        vendor="Permagen",
        invoice_date=date(2026, 1, 1),
        document_text="AFMA CONTRACT\nGoverning law of NSW\nTerms and conditions apply",
        document_heading="CONTRACT",
    )
    from app.models.invoice import Invoice

    invoice = Invoice(
        id=1,
        tenant_id=1,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        email_attachment_name="AFMA-Contract.pdf",
    )
    sample = ParsedDocumentSample(
        filename="AFMA-Contract.pdf",
        invoice=invoice,
        parsed=parsed,
        confidence="high",
    )
    catalogue = merge_draft_document_type([], proposed)
    preview = classify_parsed_sample_for_proposal_preview(
        sample,
        document_types=catalogue,
        proposed_draft=proposed,
        expected_code="DT-99",
    )
    assert preview.matches_expected is True
    assert preview.routed_code == "DT-99"


def test_proposal_matches_even_when_catalogue_routes_elsewhere() -> None:
    from datetime import date
    from app.models.invoice import Invoice, InvoiceStatus

    proposal = DocumentTypeSampleProposal(
        recognition_signals=[
            "filename_contract",
            "heading_contract",
            "text_contract",
            "text_governing_law",
            "text_terms",
        ],
        classifier_layout="supporting_doc",
        playbook_profile="supporting",
        min_route_confidence=0.55,
    )
    draft = _draft_contract_type()
    proposed = apply_sample_proposal_to_draft(draft, proposal, for_preview=True)

    parsed = InvoiceData(
        vendor="Permagen",
        invoice_no="REF-001",
        invoice_date=date(2026, 1, 1),
        total=4000,
        document_text=(
            "AFMA CONTRACT\nGoverning law of NSW\n"
            "Terms and conditions apply\npro forma payment schedule"
        ),
        document_heading="CONTRACT",
    )
    invoice = Invoice(
        id=1,
        tenant_id=1,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        email_attachment_name="AFMA Contract Draft Template - Permagen forwad EP 4k.pdf",
    )
    sample = ParsedDocumentSample(
        filename="AFMA Contract Draft Template - Permagen forwad EP 4k.pdf",
        invoice=invoice,
        parsed=parsed,
        confidence="high",
    )

    dt06 = DocumentTypeDefinition(
        code="DT-06",
        title="Proforma invoice / advance",
        shortTitle="Proforma / advance",
        klass="Pre-transactional",
        posting="Down-payment",
        fraudRisk="high",
        oneLine="Proforma is not a tax invoice.",
        routeTarget="Vault",
        classifier=build_classifier_from_signals(
            ["text_proforma", "filename_proforma"],
            "grouped",
            priority=16,
        ),
        min_route_confidence=0.65,
    )
    catalogue = merge_draft_document_type([dt06], proposed)

    assert proposed_classifier_matches_sample(proposed, sample) is True

    catalog_only = classify_parsed_sample_against_catalog(
        sample,
        document_types=catalogue,
        expected_code="DT-99",
    )
    assert catalog_only.routed_code != "DT-99"

    preview = classify_parsed_sample_for_proposal_preview(
        sample,
        document_types=catalogue,
        proposed_draft=proposed,
        expected_code="DT-99",
    )
    assert preview.matches_expected is True
    assert preview.routed_code == "DT-99"


def _tree_has_or_group(node: dict) -> bool:
    if node.get("operator") == "OR":
        return True
    for child in node.get("children") or []:
        if isinstance(child, dict) and _tree_has_or_group(child):
            return True
    return False


def test_grouped_single_signal_root_is_group() -> None:
    root = build_classifier_from_signals(["text_import"], "grouped").root
    assert root["type"] == "group"
    assert root["operator"] == "AND"
    assert len(root["children"]) == 1
    assert root["children"][0]["type"] == "condition"


def test_grouped_contract_builder_has_or_and_and() -> None:
    root = build_classifier_from_signals(
        [
            "heading_contract",
            "text_contract",
            "filename_contract",
            "text_terms",
            "text_governing_law",
        ],
        "supporting_doc",
    ).root
    assert root["operator"] == "AND"
    assert _tree_has_or_group(root)
