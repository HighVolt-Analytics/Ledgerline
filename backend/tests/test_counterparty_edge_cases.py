"""Edge-case counterparty resolution: swap, self-name, ambiguous perspective."""

from __future__ import annotations

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.classification_decision import PolicyScoreResult, ReviewReason
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.classification_compare_service import compare_classification
from app.services.extraction.llm_document_service import llm_result_to_invoice_data
from app.services.extraction.party_field_service import (
    NormalizedParty,
    apply_party_normalization_to_llm,
    maybe_correct_swapped_party_labels,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.sales.counterparty_service import (
    resolve_counterparty_name,
    resolve_counterparty_resolution,
)
from app.services.tenant.tenant_org_context import OrgContext, infer_perspective, party_matches_tenant
from app.tenant_ids import TESTING_TENANT_UUID


ORG = OrgContext(
    legal_name="Highvolt Industries Pty Ltd",
    abn="12345678901",
    aliases=["Highvolt Industries", "Highvolt"],
    default_perspective="buyer",
)


def test_party_matches_fuzzy_and_alias() -> None:
    assert party_matches_tenant("Highvolt Industries PTY LTD", "", ORG)
    assert party_matches_tenant("Highvolt", "", ORG)
    assert not party_matches_tenant("Spectra Innovations Pty Ltd", "", ORG)
    assert party_matches_tenant("Other Co", "12345678901", ORG)


def test_both_parties_match_org_is_unknown_perspective() -> None:
    assert (
        infer_perspective(
            org=ORG,
            seller_name="Highvolt Industries Pty Ltd",
            seller_abn="",
            buyer_name="Highvolt",
            buyer_abn="",
            llm_perspective="purchase",
        )
        == "unknown"
    )


def test_never_returns_tenant_as_vendor() -> None:
    resolved = resolve_counterparty_name(
        side="vendor",
        org=ORG,
        buyer_name="Highvolt Industries Pty Ltd",
        seller_name="Highvolt Industries Pty Ltd",
        generic_name="Highvolt Industries Pty Ltd",
    )
    assert resolved is None

    detail = resolve_counterparty_resolution(
        side="vendor",
        org=ORG,
        buyer_name="Highvolt Industries Pty Ltd",
        seller_name="Highvolt Industries Pty Ltd",
        generic_name="Highvolt Industries Pty Ltd",
    )
    assert detail.ambiguous is True
    assert "counterparty_self_or_missing" in detail.reasons


def test_purchase_skips_tenant_seller_uses_buyer_when_swapped_labels() -> None:
    """LLM put us in seller and real vendor in buyer — still pick non-tenant."""
    resolved = resolve_counterparty_name(
        side="vendor",
        org=ORG,
        buyer_name="Spectra Innovations Pty Ltd",
        seller_name="Highvolt Industries Pty Ltd",
        generic_name="Highvolt Industries Pty Ltd",
    )
    assert resolved == "Spectra Innovations Pty Ltd"


def test_sales_uses_seller_when_buyer_is_tenant_swap() -> None:
    """AR label swap: customer landed in seller, us in buyer."""
    resolved = resolve_counterparty_name(
        side="customer",
        org=ORG,
        buyer_name="Highvolt Industries Pty Ltd",
        seller_name="Harbour View Hotel",
        generic_name="Highvolt Industries Pty Ltd",
    )
    assert resolved == "Harbour View Hotel"


def test_ocr_layout_corrects_swapped_llm_parties() -> None:
    ocr = (
        "Spectra Innovations Pty Ltd\n"
        "TAX INVOICE\n"
        "Bill To\n"
        "Highvolt Industries Pty Ltd\n"
        "123 Factory Rd\n"
    )
    parties = {
        "seller": NormalizedParty(name="Highvolt Industries Pty Ltd"),
        "buyer": NormalizedParty(name="Spectra Innovations Pty Ltd"),
    }
    corrected, swapped = maybe_correct_swapped_party_labels(parties, ocr)
    assert swapped is True
    assert corrected["seller"].name == "Spectra Innovations Pty Ltd"
    assert corrected["buyer"].name == "Highvolt Industries Pty Ltd"


def test_apply_party_normalization_flags_ambiguous_self() -> None:
    llm = LlmDocumentResult(
        perspective="purchase",
        seller=LlmParty(name="Highvolt Industries Pty Ltd"),
        buyer=LlmParty(name="Highvolt Industries Pty Ltd"),
        vendor="Highvolt Industries Pty Ltd",
    )
    _parties, perspective, finance, fields = apply_party_normalization_to_llm(
        llm,
        ocr_text="Highvolt Industries Pty Ltd\nTAX INVOICE\n",
        org=ORG,
        route_target="Purchase Management",
    )
    assert perspective == "unknown"
    assert finance.get("vendor") is None
    assert finance.get("counterparty_ambiguous") is True
    assert fields.get("counterparty_ambiguous") == "true"


def test_llm_result_swapped_purchase_picks_real_vendor() -> None:
    ocr_text = (
        "Spectra Innovations Pty Ltd\n"
        "TAX INVOICE\n"
        "Bill To\n"
        "Highvolt Industries Pty Ltd\n"
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.9,
        perspective="purchase",
        # Intentionally swapped labels
        seller=LlmParty(name="Highvolt Industries Pty Ltd"),
        buyer=LlmParty(name="Spectra Innovations Pty Ltd"),
        vendor="Highvolt Industries Pty Ltd",
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(success=True, text=ocr_text, text_length=len(ocr_text)),
        org=ORG,
        route_target="Purchase Management",
    )
    assert parsed.vendor == "Spectra Innovations Pty Ltd"
    assert parsed.raw_fields.get("party_labels_swapped") is True


def test_compare_flags_counterparty_ambiguous() -> None:
    dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-03",
            "title": "Tax Invoice",
            "shortTitle": "Tax Inv",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "prompt",
            "recognition_signals": [],
            "llm_prompt": "Tax invoice",
            "routeTarget": "Purchase Management",
            "enabled": True,
        }
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        vendor="Highvolt Industries Pty Ltd",
    )
    parsed = InvoiceData(
        vendor="Highvolt Industries Pty Ltd",
        abn="12345678901",
        extracted_fields={"counterparty_ambiguous": "true"},
        raw_fields={"counterparty_ambiguous": True},
        document_text="TAX INVOICE",
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.95,
        perspective="purchase",
        seller=LlmParty(name="Highvolt Industries Pty Ltd"),
        buyer=LlmParty(name="Highvolt Industries Pty Ltd"),
    )
    decision = compare_classification(
        llm=llm,
        policy=PolicyScoreResult(winner_dt="DT-03", winner_confidence=0.9, scores=[]),
        invoice=inv,
        parsed=parsed,
        document_types=[dt],
        org=ORG,
    )
    assert decision.auto_eligible is False
    assert ReviewReason.COUNTERPARTY_AMBIGUOUS in decision.review_reasons
