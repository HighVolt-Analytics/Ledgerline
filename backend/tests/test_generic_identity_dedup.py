"""Generic catalogue-driven split and identity dedup tests (no production doc IDs)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.catalogue_page_signals import build_catalogue_page_matchers
from app.services.dossier.document_duplicate_service import (
    find_existing_ingest_duplicate,
    identity_overlap_duplicate_exists,
)
from app.services.extraction.document_identity_service import (
    compute_business_fingerprint,
    extract_identity_fields,
    identity_field_keys_from_catalogue,
)
from app.services.extraction.pdf_content_fingerprint import (
    compute_pdf_bytes_content_fingerprint as bytes_fp,
    compute_pdf_content_fingerprint,
)
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_service import segment_pdf_pages
from app.services.ingest.ingest_fanout_service import ingest_upload_file
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.validator import vr02_unique
from app.tenant_ids import TESTING_TENANT_UUID

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "document_types_test_catalog.json"


async def _async_cfg(catalogue: list[DocumentTypeDefinition] | None = None):
    return type("Cfg", (), {"document_types": catalogue or _load_catalogue()})()


def _load_catalogue() -> list[DocumentTypeDefinition]:
    raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return [DocumentTypeDefinition.model_validate(row) for row in raw]


def _page(index: int, text: str) -> PdfPageText:
    return PdfPageText(page_index=index, text=text)


def test_segment_bytes_fingerprint_matches_standalone_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "TAX INVOICE\nInvoice No: SYN-FP-1\nTotal $50.00\nVendor: SynthCo"
    pages = [_page(0, text)]

    monkeypatch.setattr(
        "app.services.extraction.pdf_content_fingerprint.extract_pdf_page_texts",
        lambda _path: pages,
    )
    standalone = bytes_fp(b"%PDF-synthetic-bytes")
    sliced = compute_pdf_content_fingerprint(pages, 0, 0)
    assert standalone is not None
    assert sliced is not None
    assert standalone == sliced


def test_business_fingerprint_uses_catalogue_custom_field() -> None:
    catalogue = _load_catalogue()
    keys = identity_field_keys_from_catalogue(catalogue)
    assert "po_reference" in keys

    fields = {
        "vendor": "Synth Vendor",
        "po_reference": "PO-SYN-900",
        "total": "1200.00",
    }
    if "permit_no" in keys:
        fields["permit_no"] = "PER-SYN-001"
    fp = compute_business_fingerprint(fields)
    assert fp is not None
    fp2 = compute_business_fingerprint({**fields})
    assert fp == fp2


def test_catalogue_two_document_types_split_two_page_pdf() -> None:
    catalogue = [
        DocumentTypeDefinition.model_validate(
            {
                "code": "DT-A",
                "title": "Alpha logistics sheet",
                "shortTitle": "Alpha sheet",
                "klass": "Transactional",
                "posting": "Yes",
                "oneLine": "Alpha logistics",
                "routeTarget": "Vault",
                "enabled": True,
            }
        ),
        DocumentTypeDefinition.model_validate(
            {
                "code": "DT-B",
                "title": "Beta customs sheet",
                "shortTitle": "Beta sheet",
                "klass": "Transactional",
                "posting": "Yes",
                "oneLine": "Beta customs",
                "routeTarget": "Vault",
                "enabled": True,
            }
        ),
    ]
    pages = [
        _page(0, "Alpha logistics sheet\nRef: ALP-001\nVendor: SynthCo"),
        _page(1, "Beta customs sheet\nRef: BET-002\nVendor: SynthCo"),
    ]
    segments = segment_pdf_pages(pages, document_types=catalogue)
    assert len(segments) == 2
    assert segments[0].page_kind_token == "dt:DT-A"
    assert segments[1].page_kind_token == "dt:DT-B"


def test_secondary_pass_splits_catalogue_only_page_kind() -> None:
    catalogue = [
        DocumentTypeDefinition.model_validate(
            {
                "code": "DT-REL",
                "title": "Warehouse release note",
                "shortTitle": "Release note",
                "klass": "Transactional",
                "posting": "No",
                "oneLine": "Internal warehouse release",
                "routeTarget": "Vault",
                "enabled": True,
                "classifier": {
                    "enabled": True,
                    "priority": 100,
                    "confidence": 0.8,
                    "root": {
                        "type": "group",
                        "operator": "AND",
                        "children": [
                            {
                                "type": "condition",
                                "field": "document_text",
                                "operator": "contains",
                                "value": "warehouse release note",
                            }
                        ],
                    },
                },
            }
        ),
    ]
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-SYN-44\nVendor: SynthCo"),
        _page(1, "WAREHOUSE RELEASE NOTE\nRelease Ref: REL-44\nVendor: SynthCo"),
    ]
    segments = segment_pdf_pages(pages, document_types=catalogue)
    assert len(segments) == 2
    assert segments[0].heading_kind == "purchase_order"
    assert segments[1].page_kind_token == "dt:DT-REL"


@pytest.mark.asyncio
async def test_business_fingerprint_ingest_shadow_duplicate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogue = _load_catalogue()
    keys = identity_field_keys_from_catalogue(catalogue)
    po_text = (
        "TAX INVOICE\n"
        "PO Reference: PO-SYN-771\n"
        "Vendor: Spectra Innovation\n"
        "Total USD 34410.95\n"
    )
    business_fp = compute_business_fingerprint(
        {
            "vendor": "Spectra Innovation",
            "po_reference": "PO-SYN-771",
            "total": "34410.95",
        }
    )
    assert business_fp is not None

    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="first-upload-hash",
        business_fingerprint=business_fp,
        po_reference="PO-SYN-771",
        vendor="Spectra Innovation",
        total=Decimal("34410.95"),
    )
    db_session.add(existing)
    await db_session.flush()

    monkeypatch.setenv("PDF_MULTI_DOCUMENT_SPLIT", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.load_config_for_tenant",
        lambda _s, _t: _async_cfg(catalogue),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_identity_fields_from_pdf_bytes",
        lambda _data, **kwargs: extract_identity_fields(po_text, custom_field_keys=keys),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.compute_business_fingerprint_from_bytes",
        lambda _data, **kwargs: business_fp,
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/repeat.pdf",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        tenant_name="High Volt Analytics",
        filename="repeat.pdf",
        data=b"%PDF-repeat",
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.duplicate_handled is True
    shadow = await db_session.get(Invoice, result.invoice_ids[0])
    assert shadow is not None
    assert shadow.status == InvoiceStatus.DUPLICATE_SKIPPED


@pytest.mark.asyncio
async def test_vr02_blocks_po_reference_without_invoice_no(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Synth Vendor",
        po_reference="PO-VR02-SYN",
        total=Decimal("500.00"),
        invoice_no=None,
    )
    db_session.add(existing)
    await db_session.flush()

    first = InvoiceData(
        vendor="Synth Vendor",
        po_reference="PO-VR02-SYN",
        total=Decimal("500.00"),
        currency="AUD",
    )
    assert (
        await vr02_unique(
            first,
            db_session,
            exclude_id=existing.id,
            tenant_id=TESTING_TENANT_UUID,
        )
    ).passed

    second = InvoiceData(
        vendor="Synth Vendor",
        po_reference="PO-VR02-SYN",
        total=Decimal("500.00"),
        currency="AUD",
    )
    result = await vr02_unique(second, db_session, tenant_id=TESTING_TENANT_UUID)
    assert not result.passed
    assert result.rule == "VR02"


@pytest.mark.asyncio
async def test_identity_overlap_finds_po_reference_match(db_session: AsyncSession) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Synth Vendor",
        po_reference="PO-OVERLAP-1",
        total=Decimal("99.00"),
    )
    db_session.add(existing)
    await db_session.flush()

    dup = await identity_overlap_duplicate_exists(
        db_session,
        {"vendor": "Synth Vendor", "po_reference": "PO-OVERLAP-1", "total": "99.00"},
        tenant_id=TESTING_TENANT_UUID,
    )
    assert dup is not None
    assert dup.id == existing.id


@pytest.mark.asyncio
async def test_find_existing_ingest_duplicate_checks_business_fingerprint(
    db_session: AsyncSession,
) -> None:
    business_fp = compute_business_fingerprint(
        {
            "vendor": "Synth Vendor",
            "po_reference": "PO-FP-LOOKUP",
            "total": "10.00",
        }
    )
    assert business_fp is not None

    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="other-hash",
        business_fingerprint=business_fp,
        vendor="Synth Vendor",
        po_reference="PO-FP-LOOKUP",
    )
    db_session.add(existing)
    await db_session.flush()

    found = await find_existing_ingest_duplicate(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        file_hash="new-hash",
        business_fingerprint=business_fp,
    )
    assert found is not None
    assert found.id == existing.id


def test_business_fingerprint_not_built_from_vendor_and_so_reference_only() -> None:
    fp = compute_business_fingerprint(
        {
            "vendor": "High Volt Analytics Pty Ltd",
            "so_reference": "SO-DEMO-100",
        }
    )
    assert fp is None


@pytest.mark.asyncio
async def test_identity_overlap_allows_so_sibling_documents(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Harbour View Hotel",
        so_reference="SO-DEMO-100",
        sales_document_type="dn",
    )
    db_session.add(existing)
    await db_session.flush()

    dup = await identity_overlap_duplicate_exists(
        db_session,
        {
            "vendor": "High Volt Analytics Pty Ltd",
            "so_reference": "SO-DEMO-100",
        },
        tenant_id=TESTING_TENANT_UUID,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_identity_overlap_allows_po_sibling_documents(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Synth Vendor",
        po_reference="PO-SYN-900",
        purchase_document_type="po",
    )
    db_session.add(existing)
    await db_session.flush()

    dup = await identity_overlap_duplicate_exists(
        db_session,
        {
            "vendor": "Synth Vendor",
            "po_reference": "PO-SYN-900",
        },
        tenant_id=TESTING_TENANT_UUID,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_identity_overlap_still_blocks_invoice_no_match(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Synth Vendor",
        invoice_no="INV-DUP-1",
    )
    db_session.add(existing)
    await db_session.flush()

    dup = await identity_overlap_duplicate_exists(
        db_session,
        {"invoice_no": "INV-DUP-1"},
        tenant_id=TESTING_TENANT_UUID,
    )
    assert dup is not None
    assert dup.id == existing.id


@pytest.mark.asyncio
async def test_identity_overlap_blocks_cross_register_type_with_shared_total(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Harbour View Hotel",
        so_reference="SO-DEMO-100",
        total=Decimal("450.00"),
        sales_document_type="dn",
    )
    db_session.add(existing)
    await db_session.flush()

    dup = await identity_overlap_duplicate_exists(
        db_session,
        {
            "vendor": "Harbour View Hotel",
            "so_reference": "SO-DEMO-100",
            "total": "450.00",
            "sales_document_type": "so",
        },
        tenant_id=TESTING_TENANT_UUID,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_find_existing_ingest_duplicate_allows_so_delivery_note_pair(
    db_session: AsyncSession,
) -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="delivery-note-hash",
        vendor="Harbour View Hotel",
        so_reference="SO-DEMO-100",
        sales_document_type="dn",
    )
    db_session.add(existing)
    await db_session.flush()

    found = await find_existing_ingest_duplicate(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        file_hash="sales-order-hash",
        content_fingerprint="sales-order-content-fp",
        business_fingerprint=None,
        identity_fields={
            "vendor": "High Volt Analytics Pty Ltd",
            "so_reference": "SO-DEMO-100",
        },
    )
    assert found is None
