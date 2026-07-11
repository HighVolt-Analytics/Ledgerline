"""Resolve vendor slug from email sender and parsed vendor name."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.rule_book.rule_book_mapper import load_classification_config

UNKNOWN_SLUG = "unknown"
MAX_STORAGE_SLUG_LEN = 50
_MAX_VENDOR_NAME_LEN = 100

# Parsed PDF text often mis-labels boilerplate as "vendor"; never slugify these.
_INSTRUCTION_MARKERS = (
    "please reference",
    "please quote",
    "payment terms",
    "invoice date",
    "due date",
    "bank details",
    "remittance",
    "tax invoice",
    "abn:",
    "total amount",
    "amount due",
)

# Bill of lading / transport form labels — not company names.
_FORM_LABEL_MARKERS = (
    "pre-carriage",
    "pre carriage",
    "place of",
    "port of",
    "vessel",
    "notify party",
    "consignee",
    "shipper",
    "freight payable",
    "marks and numbers",
)


def is_plausible_vendor_name(name: str | None) -> bool:
    from app.services.master_data.vendor_name_utils import is_plausible_vendor_name as _is_plausible

    return _is_plausible(name)


def is_valid_storage_slug(slug: str | None) -> bool:
    """Blob folder segment: short registry slug or 'unknown'."""
    if not slug:
        return False
    if slug == UNKNOWN_SLUG:
        return True
    if len(slug) > MAX_STORAGE_SLUG_LEN:
        return False
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug))


def slugify_vendor_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    if not slug:
        return UNKNOWN_SLUG
    if len(slug) > MAX_STORAGE_SLUG_LEN:
        trimmed = slug[:MAX_STORAGE_SLUG_LEN]
        if "-" in trimmed:
            trimmed = trimmed.rsplit("-", 1)[0]
        slug = trimmed.strip("-") or slug[:MAX_STORAGE_SLUG_LEN]
    return slug or UNKNOWN_SLUG


def _sender_matches(sender: str, pattern: str) -> bool:
    sender_l = sender.lower().strip()
    pattern_l = pattern.lower().strip()
    if not sender_l or not pattern_l:
        return False
    if pattern_l.startswith("@"):
        return sender_l.endswith(pattern_l)
    if "@" in pattern_l:
        return sender_l == pattern_l
    return sender_l.endswith(f"@{pattern_l}")


async def resolve_vendor_slug(
    session: AsyncSession,
    sender: str,
    *,
    tenant_id: int,
) -> str:
    if not sender.strip():
        return UNKNOWN_SLUG

    rows = (
        await session.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == tenant_id)
        )
    ).scalars().all()
    exact: VendorRegistry | None = None
    domain: VendorRegistry | None = None
    for row in rows:
        if not _sender_matches(sender, row.sender_pattern):
            continue
        pat = row.sender_pattern.lower().strip()
        if "@" in pat and not pat.startswith("@"):
            if sender.lower() == pat:
                exact = row
                break
        elif domain is None:
            domain = row
    match = exact or domain
    return match.vendor_slug if match else UNKNOWN_SLUG


def slug_for_parsed_vendor(vendor_name: str | None) -> str:
    if not vendor_name or not vendor_name.strip():
        return UNKNOWN_SLUG
    return slugify_vendor_name(vendor_name)


def match_rule_book_vendor_name(
    vendor_name: str | None,
    *,
    config: RuleBookConfigPayload,
) -> str | None:
    """Return canonical vendor master name when parsed text matches."""
    if not vendor_name or not vendor_name.strip():
        return None
    vendor_l = vendor_name.lower()
    for master in config.vendor_masters:
        names = [master.name, *master.aliases]
        for name in names:
            key = name.lower()
            if len(key) >= 4 and (key in vendor_l or vendor_l in key):
                return master.name
    return None


async def resolve_storage_slug_for_parsed_vendor(
    session: AsyncSession,
    parsed_vendor: str | None,
    *,
    tenant_id: int,
) -> str:
    """
    Blob folder slug after parse: registry slug for rule-book vendors,
    else registry fuzzy match, else short slugified parsed name.
    """
    if not is_plausible_vendor_name(parsed_vendor):
        return UNKNOWN_SLUG

    config = await load_classification_config(session, tenant_id)
    canonical = match_rule_book_vendor_name(parsed_vendor, config=config)
    search_name = canonical or parsed_vendor
    search_l = search_name.lower()

    rows = (
        await session.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == tenant_id)
        )
    ).scalars().all()
    for row in rows:
        row_name = row.vendor_name.lower()
        if row_name == search_l or row_name in search_l or search_l in row_name:
            return row.vendor_slug

    if canonical:
        return slugify_vendor_name(canonical)
    return slug_for_parsed_vendor(parsed_vendor)


async def find_approved_vendor(
    session: AsyncSession,
    *,
    tenant_id: int,
    vendor_name: str | None,
    sender: str | None = None,
) -> VendorRegistry | None:
    rows = (
        await session.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == tenant_id,
                VendorRegistry.approved.is_(True),
            )
        )
    ).scalars().all()
    vendor_l = (vendor_name or "").lower()
    for row in rows:
        if vendor_l and row.vendor_name.lower() in vendor_l:
            return row
        if vendor_l and vendor_l in row.vendor_name.lower():
            return row
    if sender:
        for row in rows:
            if _sender_matches(sender, row.sender_pattern):
                return row
    return None
