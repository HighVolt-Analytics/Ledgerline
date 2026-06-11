"""Vendor master signal matching (architecture §7 — Levenshtein + exact signals)."""

from __future__ import annotations

import re

from app.schemas.rule_book_config import VendorDetectionWeights, VendorMaster

NAME_FUZZY_MIN_RATIO = 0.82
ADDRESS_FUZZY_MIN_RATIO = 0.75


def levenshtein_ratio(left: str, right: str) -> float:
    """Normalized similarity 0–1 (1 = identical)."""
    a = left.strip()
    b = right.strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    distance = prev[-1]
    return 1.0 - (distance / max(len(a), len(b)))


def normalize_match_text(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", value.lower())
    return " ".join(cleaned.split())


def normalize_abn_digits(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", value.strip())


def normalize_bsb(value: str | None) -> str:
    digits = normalize_abn_digits(value)
    return digits[:6] if len(digits) >= 6 else digits


def normalize_bank_account(value: str | None) -> str:
    return normalize_abn_digits(value)


def name_signal_matches(doc_name: str, master: VendorMaster) -> bool:
    needle = normalize_match_text(doc_name)
    if len(needle) < 4:
        return False
    candidates = [master.name, *master.aliases]
    for entry in candidates:
        hay = normalize_match_text(entry)
        if len(hay) < 4:
            continue
        if levenshtein_ratio(needle, hay) >= NAME_FUZZY_MIN_RATIO:
            return True
    return False


def address_signal_matches(doc_address: str, master: VendorMaster) -> bool:
    addr = normalize_match_text(doc_address)
    if not addr:
        return False

    postcode = (master.billing_address.postcode or "").strip()
    street = normalize_match_text(master.billing_address.street or "")
    suburb = normalize_match_text(master.billing_address.suburb or "")

    if postcode and postcode not in doc_address:
        return False

    if street and (
        street in addr or levenshtein_ratio(street, addr) >= ADDRESS_FUZZY_MIN_RATIO
    ):
        return True
    if suburb and levenshtein_ratio(suburb, addr) >= ADDRESS_FUZZY_MIN_RATIO:
        return True
    if street and suburb:
        combined = f"{street} {suburb}"
        if levenshtein_ratio(combined, addr) >= ADDRESS_FUZZY_MIN_RATIO:
            return True
    return False


def bank_signal_matches(
    doc_bsb: str | None,
    doc_account: str | None,
    master: VendorMaster,
) -> bool:
    master_bsb = normalize_bsb(master.bank.bsb)
    master_account = normalize_bank_account(master.bank.account_number)
    if not master_account:
        return False

    doc_acct = normalize_bank_account(doc_account)
    if not doc_acct or doc_acct != master_account:
        return False

    master_has_bsb = bool(master_bsb)
    doc_bsb_norm = normalize_bsb(doc_bsb)
    if master_has_bsb:
        return bool(doc_bsb_norm) and doc_bsb_norm == master_bsb
    return True


def score_vendor_match(
    *,
    vendor_name: str,
    abn: str | None,
    billing_address: str | None,
    bank_bsb: str | None,
    bank_account: str | None,
    master: VendorMaster,
    weights: VendorDetectionWeights,
) -> float:
    score = 0.0
    if vendor_name.strip() and name_signal_matches(vendor_name, master):
        score += weights.name
    doc_abn = normalize_abn_digits(abn)
    master_abn = normalize_abn_digits(master.abn)
    if doc_abn and master_abn and master_abn != "PENDING" and doc_abn == master_abn:
        score += weights.abn
    if bank_signal_matches(bank_bsb, bank_account, master):
        score += weights.bank
    if billing_address and address_signal_matches(billing_address, master):
        score += weights.address
    return float(score)


def find_matching_vendor_master(
    vendor_name: str | None,
    abn: str | None,
    masters: list[VendorMaster],
) -> VendorMaster | None:
    """Return a registered master matched by ABN or fuzzy name (even below score threshold)."""
    name = (vendor_name or "").strip()
    doc_abn = normalize_abn_digits(abn)
    for master in masters:
        master_abn = normalize_abn_digits(master.abn)
        if doc_abn and master_abn and master_abn != "PENDING" and doc_abn == master_abn:
            return master
    if not name:
        return None
    for master in masters:
        if name_signal_matches(name, master):
            return master
    return None
