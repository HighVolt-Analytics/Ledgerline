"""Config-driven counterparty resolution."""

from __future__ import annotations

from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.services.extraction.party_field_service import apply_party_normalization_to_llm
from app.services.tenant.tenant_org_context import OrgContext

_PACKING_LIST_OCR = """spectra Innovations Pte Ltd
217 Henderson Road, #03-10, Singapore 159555
PACKING LIST
WALTON DIGI-TECH INDUSTRIES LIMITED CHANDRA,KALIAKAIR,PS,GAZIPUR-1750, BANGLADESH.
INVOICE NO. : 260371344/
"""


def test_consignee_counterparty_source_prefers_buyer_over_letterhead() -> None:
    llm = LlmDocumentResult(
        vendor="spectra Innovations Pte Ltd",
        seller=LlmParty(name="spectra Innovations Pte Ltd"),
        buyer=LlmParty(name="WALTON DIGI-TECH INDUSTRIES LIMITED"),
    )
    _parties, _perspective, finance, _fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=_PACKING_LIST_OCR,
        org=OrgContext(),
        counterparty_source="consignee",
        route_target="Sales Management",
    )
    assert "WALTON" in (finance.get("vendor") or "").upper()


def test_letterhead_counterparty_source_keeps_seller_on_commercial_invoice() -> None:
    ocr = """Acme Pty Ltd
Tax Invoice
Bill To: Buyer Co
Invoice No: INV-1
"""
    llm = LlmDocumentResult(
        vendor="Acme Pty Ltd",
        seller=LlmParty(name="Acme Pty Ltd"),
        buyer=LlmParty(name="Buyer Co"),
    )
    _parties, _perspective, finance, _fields = apply_party_normalization_to_llm(
        llm,
        ocr_text=ocr,
        org=OrgContext(default_perspective="purchase"),
        counterparty_source="letterhead",
        route_target="Purchase Management",
    )
    assert "Acme" in (finance.get("vendor") or "")
