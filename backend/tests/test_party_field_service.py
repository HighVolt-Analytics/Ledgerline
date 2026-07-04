"""Universal party field normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.llm_document_service import llm_result_to_invoice_data
from app.services.extraction.party_field_service import (
    apply_party_normalization_to_llm,
    parties_from_llm,
    sanitize_address,
    tax_id_grounded_in_ocr,
)
from app.services.extraction.pdf_parser import parse_local_text
from app.services.tenant.tenant_org_context import OrgContext

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "commercial_invoice_spectra_ryans.txt"


@pytest.fixture
def spectra_ryans_text() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_sanitize_address_strips_compliance_bleed(spectra_ryans_text: str) -> None:
    polluted = (
        "238/1, KUSHOLI BHABAN, WEST KAFRUL, BEGUM ROKEYA SARANI, TALTALA, DHAKA-1207, BANGLADESH "
        "HS CODE NO: 8523.51.10, 8471.70.00 APPLICANT'S IRC NO: 260326112587425"
    )
    cleaned = sanitize_address(polluted)
    assert "HS CODE" not in cleaned
    assert "IRC NO" not in cleaned
    assert "DHAKA-1207" in cleaned


def test_tax_id_grounded_rejects_hallucinated_abn(spectra_ryans_text: str) -> None:
    assert not tax_id_grounded_in_ocr("45123456789", spectra_ryans_text)
    assert tax_id_grounded_in_ocr("199904042N", spectra_ryans_text)


def test_parties_from_llm_reject_ungrounded_buyer_tax_id(spectra_ryans_text: str) -> None:
    llm = LlmDocumentResult(
        seller=LlmParty(name="Spectra Innovations Pte Ltd", tax_id="199904042N"),
        buyer=LlmParty(name="RYANS COMPUTERS LIMITED", tax_id="45123456789"),
        perspective="purchase",
    )
    parties = parties_from_llm(llm, spectra_ryans_text)
    assert parties["seller"].tax_id == "199904042N"
    assert parties["buyer"].tax_id == ""


def test_apply_party_normalization_commercial_invoice(spectra_ryans_text: str) -> None:
    llm = LlmDocumentResult(
        seller=LlmParty(
            name="Spectra Innovations Pte Ltd",
            tax_id="199904042N",
            address="217 HENDERSON ROAD #03-10, SINGAPORE 159555",
        ),
        buyer=LlmParty(
            name="RYANS COMPUTERS LIMITED",
            tax_id="45123456789",
            address=(
                "238/1, KUSHOLI BHABAN, WEST KAFRUL, BEGUM ROKEYA SARANI, "
                "TALTALA, DHAKA-1207, BANGLADESH HS CODE NO: 8523.51.10"
            ),
        ),
        perspective="purchase",
        invoice_no="250970286",
        vendor="Spectra Innovations Pte Ltd",
    )
    _parties, perspective, finance, fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=spectra_ryans_text,
        org=OrgContext(),
    )
    assert perspective == "purchase"
    assert finance["vendor"] == "Spectra Innovations Pte Ltd"
    assert finance.get("abn") is None  # Singapore reg is not 11-digit ABN
    assert "HS CODE" not in (finance.get("billing_address") or "")
    assert fields["seller_name"] == "Spectra Innovations Pte Ltd"
    assert fields["buyer_name"] == "RYANS COMPUTERS LIMITED"
    assert fields.get("buyer_abn", "") == ""


def test_llm_result_to_invoice_data_uses_party_normalization(spectra_ryans_text: str) -> None:
    llm = LlmDocumentResult(
        seller=LlmParty(name="Spectra Innovations Pte Ltd", tax_id="199904042N"),
        buyer=LlmParty(name="RYANS COMPUTERS LIMITED", tax_id="45123456789"),
        perspective="purchase",
        vendor="Spectra Innovations Pte Ltd",
    )
    ocr = OcrArtifact(text=spectra_ryans_text, text_length=len(spectra_ryans_text))
    parsed = llm_result_to_invoice_data(llm, ocr=ocr, org=OrgContext())
    assert parsed.vendor == "Spectra Innovations Pte Ltd"
    assert parsed.extracted_fields.get("buyer_abn", "") == ""


def test_parse_local_text_extracts_applicant_address(spectra_ryans_text: str) -> None:
    parsed = parse_local_text(spectra_ryans_text)
    assert parsed.billing_address
    assert "HS CODE" not in parsed.billing_address
    assert "DHAKA" in parsed.billing_address.upper()
    assert parsed.extracted_fields.get("buyer_name") == "RYANS COMPUTERS LIMITED"
