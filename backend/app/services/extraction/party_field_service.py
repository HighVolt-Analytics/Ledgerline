"""Universal party field normalization — addresses, tax IDs, finance scalars."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.jurisdiction.packs import JurisdictionPack, jurisdiction_pack_for_country
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.services.tenant.tenant_org_context import OrgContext, infer_perspective
from app.tenant_settings import DEFAULT_COUNTRY
from app.utils.tax_id_validator import is_acceptable_tax_id

_ADDRESS_BLEED_MARKERS = re.compile(
    r"\b(?:HS\s*CODE|APPLICANT'?S?\s+IRC|BIN\s*:|TIN\s*:|DOCUMENTARY\s+CREDIT|"
    r"ISSUING\s+BANK|DELIVERY\s+TERMS|DISCHARGE\s+PORT|PORT\s+OF\s+LOADING|"
    r"SHIPPING\s+MARK|TRADE\s+TERM|INSURANCE\s+COVER|COMPUTER\s+PARTS)\b",
    re.I,
)


def party_llm_rules(pack: JurisdictionPack | None = None) -> str:
    """Jurisdiction-aware party prompt fragment."""
    p = pack or jurisdiction_pack_for_country(DEFAULT_COUNTRY)
    return (
        "- seller and buyer are objects with name, tax_id, and address "
        "(multi-line address as one string).\n"
        "- Copy tax_id and address verbatim from OCR; leave empty if absent.\n"
        f"- Never invent tax IDs or {p.llm_tax_id_examples}.\n"
        f"- tax_id is jurisdiction-aware for this tenant ({p.tax_id_label}); also accept "
        "ABN, GSTIN, VAT, BIN, TIN, EIN, Company Reg, etc. when printed on the document.\n"
        "- On commercial/export invoices: seller = issuer/exporter in header; "
        "buyer = consignee/applicant/bill-to.\n"
        "- Put buyer bill-to address in buyer.address; do not include HS codes, LC refs, "
        "or customs metadata in addresses."
    )


# Default rules use platform DEFAULT_COUNTRY (SG pack when org country unset).
PARTY_LLM_RULES = party_llm_rules()


@dataclass(frozen=True)
class NormalizedParty:
    name: str = ""
    tax_id: str = ""
    address: str = ""


def sanitize_address(text: str | None) -> str:
    """Trim address text and stop at compliance / customs bleed markers."""
    if not text:
        return ""
    cleaned = " ".join(line.strip() for line in str(text).splitlines() if line.strip())
    match = _ADDRESS_BLEED_MARKERS.search(cleaned)
    if match:
        cleaned = cleaned[: match.start()].strip(" ,;")
    return cleaned[:500]


def tax_id_grounded_in_ocr(tax_id: str | None, ocr_text: str | None) -> bool:
    """True when tax_id is empty or appears in OCR (rejects hallucinated IDs)."""
    if not tax_id or not str(tax_id).strip():
        return True
    if not ocr_text:
        return False
    tid = str(tax_id).strip()
    norm_tid = re.sub(r"[^A-Z0-9]", "", tid.upper())
    norm_ocr = re.sub(r"[^A-Z0-9]", "", ocr_text.upper())
    if norm_tid and len(norm_tid) >= 4 and norm_tid in norm_ocr:
        return True
    digits = "".join(c for c in tid if c.isdigit())
    if len(digits) >= 8:
        if re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", ocr_text):
            return True
    return False


def normalize_party_fields(
    *,
    name: str | None = None,
    tax_id: str | None = None,
    address: str | None = None,
    ocr_text: str | None = None,
    tax_id_kind: str | None = None,
) -> NormalizedParty:
    from app.services.extraction.field_grounding_service import value_grounded_in_ocr

    addr = sanitize_address(address)
    name = (name or "").strip()
    if name and ocr_text and not value_grounded_in_ocr(name, ocr_text):
        name = ""
    tid = str(tax_id or "").strip()
    if tid and not tax_id_grounded_in_ocr(tid, ocr_text):
        tid = ""
    if tid and not is_acceptable_tax_id(tid, tax_id_kind=tax_id_kind):
        # Allow grounded non-checksum IDs when kind is unset/generic
        if tax_id_kind and tax_id_kind not in {"generic", ""}:
            tid = ""
        elif not tax_id_grounded_in_ocr(tid, ocr_text):
            tid = ""
    return NormalizedParty(name=(name or "").strip(), tax_id=tid, address=addr)


def normalize_llm_party(
    party: LlmParty,
    ocr_text: str | None,
    *,
    tax_id_kind: str | None = None,
) -> NormalizedParty:
    return normalize_party_fields(
        name=party.name,
        tax_id=party.tax_id or party.abn,
        address=party.address,
        ocr_text=ocr_text,
        tax_id_kind=tax_id_kind,
    )


def parties_from_llm(
    llm: LlmDocumentResult,
    ocr_text: str | None,
    *,
    tax_id_kind: str | None = None,
) -> dict[str, NormalizedParty]:
    return {
        "seller": normalize_llm_party(llm.seller, ocr_text, tax_id_kind=tax_id_kind),
        "buyer": normalize_llm_party(llm.buyer, ocr_text, tax_id_kind=tax_id_kind),
    }


def party_extracted_fields_dict(parties: dict[str, NormalizedParty]) -> dict[str, str]:
    """Canonical extracted_fields keys for seller/buyer parties."""
    out: dict[str, str] = {}
    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()
    if seller.name:
        out["seller_name"] = seller.name
    if seller.tax_id:
        out["seller_tax_id"] = seller.tax_id
        out["seller_abn"] = seller.tax_id
    if seller.address:
        out["seller_address"] = seller.address
    if buyer.name:
        out["buyer_name"] = buyer.name
    if buyer.tax_id:
        out["buyer_tax_id"] = buyer.tax_id
        out["buyer_abn"] = buyer.tax_id
    if buyer.address:
        out["buyer_address"] = buyer.address
    return out


def enrich_parties_from_ocr_text(
    parties: dict[str, NormalizedParty],
    ocr_text: str | None,
) -> dict[str, NormalizedParty]:
    """Fill empty party fields from regex extractors on OCR text."""
    from app.services.extraction.field_grounding_service import value_grounded_in_ocr
    from app.services.master_data.vendor_name_utils import (
        extract_buyer_address_from_text,
        extract_buyer_party_from_text,
        extract_header_vendor,
        extract_seller_address_from_text,
    )

    if not ocr_text:
        return parties

    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()

    seller_name = seller.name
    if not seller_name:
        candidate = extract_header_vendor(ocr_text)
        if candidate and value_grounded_in_ocr(candidate, ocr_text):
            seller_name = candidate
    buyer_name = buyer.name
    if not buyer_name:
        candidate = extract_buyer_party_from_text(ocr_text)
        if candidate and value_grounded_in_ocr(candidate, ocr_text):
            buyer_name = candidate
    seller_address = seller.address
    if not seller_address:
        candidate = extract_seller_address_from_text(ocr_text)
        if candidate and value_grounded_in_ocr(candidate, ocr_text):
            seller_address = candidate
    buyer_address = buyer.address
    if not buyer_address:
        candidate = extract_buyer_address_from_text(ocr_text)
        if candidate and value_grounded_in_ocr(candidate, ocr_text):
            buyer_address = candidate

    return {
        "seller": NormalizedParty(
            name=seller_name,
            tax_id=seller.tax_id,
            address=sanitize_address(seller_address),
        ),
        "buyer": NormalizedParty(
            name=buyer_name,
            tax_id=buyer.tax_id,
            address=sanitize_address(buyer_address),
        ),
    }


def resolve_perspective(
    parties: dict[str, NormalizedParty],
    llm: LlmDocumentResult,
    org: OrgContext,
) -> str:
    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()
    return infer_perspective(
        org=org,
        seller_name=seller.name,
        seller_abn=seller.tax_id,
        buyer_name=buyer.name,
        buyer_abn=buyer.tax_id,
        llm_perspective=llm.perspective or "unknown",
    )


def resolve_finance_scalars(
    parties: dict[str, NormalizedParty],
    *,
    perspective: str,
    org: OrgContext,
    llm: LlmDocumentResult,
    ocr_text: str | None,
    counterparty_source: str = "letterhead",
    route_target: str | None = None,
) -> dict[str, Any]:
    """Perspective-aware vendor, abn, and billing_address."""
    from app.services.sales.counterparty_service import (
        resolve_counterparty_name,
        resolve_counterparty_side,
    )
    from app.services.master_data.vendor_resolver import is_plausible_vendor_name
    from app.utils.tax_id_validator import storage_tax_id

    pack = jurisdiction_pack_for_country(org.country)
    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()

    source = (counterparty_source or "letterhead").strip().lower()
    if source in {"consignee", "applicant", "bill_to"}:
        side = "customer"
    else:
        side = resolve_counterparty_side(route_target=route_target, perspective=perspective)

    buyer_name = buyer.name
    if source == "applicant" and ocr_text:
        from app.services.master_data.vendor_name_utils import extract_buyer_party_from_text

        applicant = extract_buyer_party_from_text(ocr_text)
        if applicant:
            buyer_name = applicant or buyer_name
    elif source == "bill_to" and buyer.address and not buyer_name:
        buyer_name = buyer.name

    vendor = resolve_counterparty_name(
        side=side,
        org=org,
        buyer_name=buyer_name,
        buyer_abn=buyer.tax_id,
        seller_name=seller.name,
        seller_abn=seller.tax_id,
        generic_name=llm.vendor,
        document_text=ocr_text,
    )
    if not is_plausible_vendor_name(vendor):
        for candidate in (seller.name, buyer.name, llm.vendor):
            token = (candidate or "").strip()
            if is_plausible_vendor_name(token):
                vendor = token
                break

    counterparty_tax_id = ""
    if perspective == "sales":
        counterparty_tax_id = buyer.tax_id
    elif perspective == "purchase":
        counterparty_tax_id = seller.tax_id
    else:
        counterparty_tax_id = seller.tax_id or buyer.tax_id

    top_level = str(llm.abn or "").strip()
    if top_level and tax_id_grounded_in_ocr(top_level, ocr_text):
        counterparty_tax_id = top_level or counterparty_tax_id

    abn = (
        storage_tax_id(counterparty_tax_id, tax_id_kind=pack.tax_id_kind)
        if counterparty_tax_id
        else None
    )
    billing = sanitize_address(buyer.address) or None

    return {
        "vendor": vendor,
        "abn": abn,
        "billing_address": billing,
        "counterparty_tax_id": counterparty_tax_id or None,
    }


def apply_party_normalization_to_llm(
    llm: LlmDocumentResult,
    *,
    ocr_text: str | None,
    org: OrgContext | None = None,
    counterparty_source: str = "letterhead",
    route_target: str | None = None,
) -> tuple[dict[str, NormalizedParty], str, dict[str, Any], dict[str, str]]:
    """
    Full party pipeline: normalize, enrich from OCR, resolve perspective and scalars.

    Returns (parties, perspective, finance_scalars, extracted_party_fields).
    """
    org_ctx = org or OrgContext()
    pack = jurisdiction_pack_for_country(org_ctx.country)
    parties = parties_from_llm(llm, ocr_text, tax_id_kind=pack.tax_id_kind)
    parties = enrich_parties_from_ocr_text(parties, ocr_text)
    perspective = resolve_perspective(parties, llm, org_ctx)
    finance = resolve_finance_scalars(
        parties,
        perspective=perspective,
        org=org_ctx,
        llm=llm,
        ocr_text=ocr_text,
        counterparty_source=counterparty_source,
        route_target=route_target,
    )
    extracted = party_extracted_fields_dict(parties)
    if finance.get("billing_address"):
        extracted.setdefault("billing_address", str(finance["billing_address"]))
    return parties, perspective, finance, extracted
