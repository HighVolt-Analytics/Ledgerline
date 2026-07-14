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
    from app.services.master_data.vendor_name_utils import (
        dedupe_repeated_vendor_phrase,
        is_plausible_vendor_name,
        strip_vendor_name_contamination,
    )
    import re

    def _label(name: str) -> str:
        if not name:
            return ""
        cleaned = strip_vendor_name_contamination(dedupe_repeated_vendor_phrase(name))
        if not is_plausible_vendor_name(cleaned):
            return ""
        return re.sub(r"\s+", " ", cleaned.strip())

    out: dict[str, str] = {}
    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()
    seller_name = _label(seller.name)
    if seller_name:
        out["seller_name"] = seller_name
    if seller.tax_id:
        out["seller_tax_id"] = seller.tax_id
        out["seller_abn"] = seller.tax_id
    if seller.address:
        out["seller_address"] = seller.address
    buyer_name = _label(buyer.name)
    if buyer_name:
        out["buyer_name"] = buyer_name
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


def _names_fuzzy_equal(left: str, right: str) -> bool:
    from app.services.master_data.vendor_detection import (
        NAME_FUZZY_MIN_RATIO,
        levenshtein_ratio,
        normalize_match_text,
    )

    a = normalize_match_text(left or "")
    b = normalize_match_text(right or "")
    if not a or not b or len(a) < 4 or len(b) < 4:
        return False
    if a == b or a in b or b in a:
        return True
    return levenshtein_ratio(a, b) >= NAME_FUZZY_MIN_RATIO


def maybe_correct_swapped_party_labels(
    parties: dict[str, NormalizedParty],
    ocr_text: str | None,
) -> tuple[dict[str, NormalizedParty], bool]:
    """
    Fix LLM seller/buyer swaps when OCR layout signals disagree with labels.

    Uses letterhead (issuer) vs Bill-To/customer blocks. Only swaps when both
    OCR anchors exist and clearly cross-match the LLM parties.
    """
    if not ocr_text:
        return parties, False

    from app.services.master_data.vendor_name_utils import (
        extract_buyer_party_from_text,
        extract_customer_party_from_text,
        extract_header_vendor,
        extract_supplier_party_from_text,
    )

    seller = parties.get("seller") or NormalizedParty()
    buyer = parties.get("buyer") or NormalizedParty()
    if not seller.name or not buyer.name:
        return parties, False

    ocr_seller = (
        extract_header_vendor(ocr_text)
        or extract_supplier_party_from_text(ocr_text)
        or ""
    )
    ocr_buyer = (
        extract_customer_party_from_text(ocr_text)
        or extract_buyer_party_from_text(ocr_text)
        or ""
    )
    if not ocr_seller or not ocr_buyer:
        return parties, False
    if _names_fuzzy_equal(ocr_seller, ocr_buyer):
        return parties, False

    llm_aligned = _names_fuzzy_equal(seller.name, ocr_seller) and _names_fuzzy_equal(
        buyer.name, ocr_buyer
    )
    llm_crossed = _names_fuzzy_equal(seller.name, ocr_buyer) and _names_fuzzy_equal(
        buyer.name, ocr_seller
    )
    if llm_crossed and not llm_aligned:
        return {"seller": buyer, "buyer": seller}, True
    return parties, False


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
        resolve_counterparty_resolution,
        resolve_counterparty_side,
    )
    from app.services.master_data.vendor_name_utils import is_plausible_vendor_name
    from app.services.tenant.tenant_org_context import party_matches_tenant
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

    resolution = resolve_counterparty_resolution(
        side=side,
        org=org,
        buyer_name=buyer_name,
        buyer_abn=buyer.tax_id,
        seller_name=seller.name,
        seller_abn=seller.tax_id,
        generic_name=llm.vendor,
        document_text=ocr_text,
        perspective=perspective,
    )
    vendor = resolution.name
    ambiguous = resolution.ambiguous or perspective == "unknown"
    reasons = list(resolution.reasons)
    if perspective == "unknown" and "perspective_unknown" not in reasons:
        reasons.append("perspective_unknown")

    if vendor and not is_plausible_vendor_name(vendor):
        vendor = None
    if not vendor:
        for candidate, tax_id in (
            (seller.name, seller.tax_id),
            (buyer.name, buyer.tax_id),
            (llm.vendor, ""),
        ):
            token = (candidate or "").strip()
            if not is_plausible_vendor_name(token):
                continue
            if party_matches_tenant(token, tax_id or "", org):
                continue
            vendor = token
            break
        if not vendor:
            ambiguous = True
            if "counterparty_self_or_missing" not in reasons:
                reasons.append("counterparty_self_or_missing")

    # Tax id should follow the counterparty side, not the tenant.
    counterparty_tax_id = ""
    if side == "customer" or perspective == "sales":
        if vendor and _names_fuzzy_equal(vendor, buyer.name):
            counterparty_tax_id = buyer.tax_id
        elif vendor and _names_fuzzy_equal(vendor, seller.name):
            counterparty_tax_id = seller.tax_id
        else:
            counterparty_tax_id = buyer.tax_id or seller.tax_id
    elif side == "vendor" or perspective == "purchase":
        if vendor and _names_fuzzy_equal(vendor, seller.name):
            counterparty_tax_id = seller.tax_id
        elif vendor and _names_fuzzy_equal(vendor, buyer.name):
            counterparty_tax_id = buyer.tax_id
        else:
            counterparty_tax_id = seller.tax_id or buyer.tax_id
    else:
        counterparty_tax_id = seller.tax_id or buyer.tax_id

    top_level = str(llm.abn or "").strip()
    if top_level and tax_id_grounded_in_ocr(top_level, ocr_text):
        # Only keep top-level tax id when it does not match the tenant.
        if not party_matches_tenant("", top_level, org):
            counterparty_tax_id = top_level or counterparty_tax_id

    if counterparty_tax_id and party_matches_tenant("", counterparty_tax_id, org):
        # Prefer the non-tenant party's tax id.
        if not party_matches_tenant(seller.name, seller.tax_id, org) and seller.tax_id:
            counterparty_tax_id = seller.tax_id
        elif not party_matches_tenant(buyer.name, buyer.tax_id, org) and buyer.tax_id:
            counterparty_tax_id = buyer.tax_id
        else:
            counterparty_tax_id = ""

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
        "counterparty_ambiguous": ambiguous,
        "counterparty_review_reasons": reasons,
        "counterparty_side": side,
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
    parties, swapped = maybe_correct_swapped_party_labels(parties, ocr_text)
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
    if swapped:
        review_reasons = list(finance.get("counterparty_review_reasons") or [])
        if "party_labels_swapped" not in review_reasons:
            review_reasons.append("party_labels_swapped")
        finance = {
            **finance,
            "party_labels_swapped": True,
            "counterparty_review_reasons": review_reasons,
        }
    extracted = party_extracted_fields_dict(parties)
    extracted["perspective"] = perspective
    if finance.get("billing_address"):
        extracted.setdefault("billing_address", str(finance["billing_address"]))
    if finance.get("counterparty_ambiguous"):
        extracted["counterparty_ambiguous"] = "true"
    if finance.get("party_labels_swapped"):
        extracted["party_labels_swapped"] = "true"
    return parties, perspective, finance, extracted
