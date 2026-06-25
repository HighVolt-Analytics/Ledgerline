"""Tests for vendor slug resolution and blob path helpers."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.services.account_mapper import clear_rule_book_cache
from app.services.rule_book_mapper import clear_classification_config_cache
from app.services import blob_storage
from app.services.vendor_resolver import (
    UNKNOWN_SLUG,
    is_plausible_vendor_name,
    is_valid_storage_slug,
    match_rule_book_vendor_name,
    resolve_storage_slug_for_parsed_vendor,
    resolve_vendor_slug,
    slug_for_parsed_vendor,
    slugify_vendor_name,
)


def test_slugify_vendor_name() -> None:
    assert slugify_vendor_name("Atlassian Pty Ltd") == "atlassian-pty-ltd"
    assert slug_for_parsed_vendor("Amazon Web Services") == "amazon-web-services"
    assert slug_for_parsed_vendor(None) == UNKNOWN_SLUG


def test_is_plausible_vendor_name_rejects_boilerplate() -> None:
    assert not is_plausible_vendor_name(
        "Invoice Date: Please reference the invoice number with payment"
    )
    assert is_plausible_vendor_name("Atlassian Pty Ltd")


def test_is_valid_storage_slug() -> None:
    assert is_valid_storage_slug("atlassian")
    assert is_valid_storage_slug("unknown")
    assert not is_valid_storage_slug(
        "invoice-date-please-reference-the-invoice-number-with-payment"
    )


@pytest.mark.asyncio
async def test_resolve_storage_slug_rejects_boilerplate(db_session: AsyncSession) -> None:
    slug = await resolve_storage_slug_for_parsed_vendor(
        db_session,
        "Invoice Date: Please reference the invoice number with payment",
        tenant_id=1,
    )
    assert slug == UNKNOWN_SLUG


def test_match_rule_book_vendor_name() -> None:
    clear_rule_book_cache()
    clear_classification_config_cache()
    assert (
        match_rule_book_vendor_name("Amazon Web Services", tenant_id=1)
        == "Amazon Web Services"
    )
    assert match_rule_book_vendor_name("SYSCO AU", tenant_id=1) == "Sysco Australia"
    assert match_rule_book_vendor_name("Random Corp", tenant_id=1) is None


@pytest.mark.asyncio
async def test_resolve_storage_slug_rule_book_registry(db_session: AsyncSession) -> None:
    db_session.add(
        VendorRegistry(
            tenant_id=1,
            vendor_slug="qantas",
            vendor_name="Qantas Airways Limited",
            sender_pattern="@qantas.com.au",
            approved=False,
        )
    )
    await db_session.flush()
    slug = await resolve_storage_slug_for_parsed_vendor(
        db_session, "Qantas", tenant_id=1
    )
    assert slug == "qantas"


@pytest.mark.asyncio
async def test_resolve_vendor_slug_exact(db_session: AsyncSession) -> None:
    db_session.add(
        VendorRegistry(
            tenant_id=1,
            vendor_slug="atlassian",
            vendor_name="Atlassian Pty Ltd",
            sender_pattern="billing@atlassian.com",
            approved=True,
        )
    )
    await db_session.flush()
    slug = await resolve_vendor_slug(db_session, "billing@atlassian.com", tenant_id=1)
    assert slug == "atlassian"


@pytest.mark.asyncio
async def test_resolve_vendor_slug_domain(db_session: AsyncSession) -> None:
    db_session.add(
        VendorRegistry(
            tenant_id=1,
            vendor_slug="atlassian",
            vendor_name="Atlassian Pty Ltd",
            sender_pattern="@atlassian.com",
            approved=True,
        )
    )
    await db_session.flush()
    slug = await resolve_vendor_slug(db_session, "noreply@atlassian.com", tenant_id=1)
    assert slug == "atlassian"


@pytest.mark.asyncio
async def test_resolve_vendor_slug_unknown(db_session: AsyncSession) -> None:
    slug = await resolve_vendor_slug(db_session, "random@example.com", tenant_id=1)
    assert slug == UNKNOWN_SLUG


from app.tenant_ids import TESTING_TENANT_UUID

_TID = TESTING_TENANT_UUID


def test_build_blob_name() -> None:
    from datetime import date

    name = blob_storage.build_blob_name(
        _TID,
        "hv-org",
        "atlassian",
        42,
        "abc123def456",
        "invoice.pdf",
        tenant_name="High Volt Analytics",
        vendor_name="Atlassian Pty Ltd",
        invoice_no="INV-042",
        invoice_date=date(2026, 5, 4),
        route_target="Expenses Management",
    )
    from app.services.tenant_storage_paths import tenant_root

    prefix = f"{tenant_root(_TID)}/"
    assert (
        name
        == f"{prefix}invoice/Expenses Management/Atlassian Pty Ltd/2026/May/INV-042_2026-05-04_id42.pdf"
    )


def test_stored_uri_roundtrip() -> None:
    uri = blob_storage.to_stored_uri(
        "invoice/Expenses Management/Atlassian Pty Ltd/2026/May/INV-042_2026-05-04_id42.pdf"
    )
    parsed = blob_storage.parse_stored_uri(uri)
    assert parsed is not None
    assert parsed[1].endswith("INV-042_2026-05-04_id42.pdf")
