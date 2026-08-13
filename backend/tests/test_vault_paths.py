"""Tests for vault folder path helpers."""

from datetime import date

from app.services.tenant.tenant_storage_paths import tenant_root
from app.services.vault.vault_paths import (
    ROUTE_PURCHASE,
    ROUTE_VAULT,
    ROUTE_UNROUTED,
    build_vault_blob_name,
    build_vault_tree,
    extract_upload_timestamp_ms,
    filename_from_stored,
    insert_org_segment_into_blob_path,
    strip_org_segment_from_blob_path,
    vault_book_folder,
    vault_document_type_folder,
    vault_file_name,
    vault_month,
    vault_tenant_folder,
    vault_vendor_folder,
)


from app.tenant_ids import TESTING_TENANT_UUID

_TID = TESTING_TENANT_UUID
_PREFIX = f"{tenant_root(_TID)}/"


def test_vault_tenant_folder() -> None:
    assert vault_tenant_folder("hv-org") == "HvOrg"


def test_vault_book_folder() -> None:
    assert vault_book_folder(ROUTE_PURCHASE) == "Purchase Management"
    assert vault_book_folder(None) == ROUTE_UNROUTED
    assert vault_book_folder("") == ROUTE_UNROUTED


def test_vault_book_folder_normalizes_type_case_variants() -> None:
    from app.services.vault.vault_paths import normalize_vault_type_book_label

    assert normalize_vault_type_book_label("PACKING LIST") == "Packing List"
    assert normalize_vault_type_book_label("Packing List") == "Packing List"
    assert normalize_vault_type_book_label("Warehouse Gate Pass") == "Warehouse Gate Pass"
    assert vault_book_folder("PACKING LIST") == vault_book_folder("Packing List")
    assert vault_book_folder("BILL OF LADING") == "Bill of Lading"
    assert vault_book_folder("CERTIFICATE OF ORIGIN") == "Certificate of Origin"


def test_vault_vendor_folder_display_name() -> None:
    assert vault_vendor_folder("Atlassian Pty Ltd") == "Atlassian Pty Ltd"
    assert vault_vendor_folder(None, "atlassian-pty-ltd") == "Atlassian Pty Ltd"


def test_vault_month_name_only() -> None:
    assert vault_month(date(2026, 5, 4)) == "May"


def test_build_vault_blob_name() -> None:
    path = build_vault_blob_name(
        _TID,
        "hv-org",
        tenant_name="HV Org",
        route_target=ROUTE_PURCHASE,
        vendor_name="James Patel Consulting",
        storage_vendor_slug="james-patel",
        invoice_id=7,
        invoice_no="INV-007",
        invoice_date=date(2026, 5, 12),
        original_filename="scan.pdf",
    )
    assert (
        path
        == f"{_PREFIX}invoice/Purchase Management/James Patel Consulting/2026/May/INV-007_2026-05-12_id7.pdf"
    )


def test_build_vault_blob_name_with_document_type() -> None:
    path = build_vault_blob_name(
        _TID,
        "hv-org",
        route_target=ROUTE_VAULT,
        vendor_name="ATO",
        invoice_id=9,
        invoice_no="GST-001",
        invoice_date=date(2026, 4, 1),
        original_filename="notice.pdf",
        document_type_code="DT-25",
        document_type_short_title="Tax authority notice",
    )
    assert (
        path
        == f"{_PREFIX}invoice/Vault/DT-25  -  Tax authority notice/ATO/2026/April/GST-001_2026-04-01_id9.pdf"
    )


def test_vault_document_type_folder_label() -> None:
    assert vault_document_type_folder("DT-13", short_title="Vendor statement") == (
        "DT-13  -  Vendor statement"
    )


def test_purchase_blob_name_flat_with_shared_po_in_filename() -> None:
    path = build_vault_blob_name(
        _TID,
        "hv-org",
        route_target=ROUTE_PURCHASE,
        vendor_name="Sysco Australia",
        invoice_id=102,
        invoice_no="GRN-8842",
        invoice_date=date(2026, 6, 3),
        original_filename="grn.pdf",
        po_reference="PO-MKT-2026-014",
        purchase_document_type="grn",
    )
    assert path.endswith("GRN_PO-MKT-2026-014_2026-06-03_id102.pdf")
    assert "PO-MKT-2026-014/" not in path


def test_vault_file_name_uses_po_reference_for_purchase_docs() -> None:
    assert (
        vault_file_name(
            "GRN-8842",
            102,
            date(2026, 6, 3),
            "grn.pdf",
            purchase_document_type="grn",
            po_reference="PO-MKT-2026-014",
        )
        == "GRN_PO-MKT-2026-014_2026-06-03_id102.pdf"
    )
    assert (
        vault_file_name(
            "INV-9921",
            103,
            date(2026, 6, 5),
            "inv.pdf",
            purchase_document_type="invoice",
            po_reference="PO-MKT-2026-014",
        )
        == "INV_PO-MKT-2026-014_2026-06-05_id103.pdf"
    )


def test_vault_file_name_unique_for_shared_invoice_no() -> None:
    shared_no = "260671582"
    a = vault_file_name(shared_no, 21, None, "part1.pdf")
    b = vault_file_name(shared_no, 22, None, "part2.pdf")
    assert a != b
    assert a.endswith("_id21.pdf")
    assert b.endswith("_id22.pdf")


def test_extract_upload_timestamp_ms() -> None:
    assert extract_upload_timestamp_ms("INV-007_2026-05-12_id7_1712345678901.pdf") == (
        "1712345678901"
    )
    assert extract_upload_timestamp_ms("scan.pdf") is None
    assert extract_upload_timestamp_ms("INV-007_2026-05-12_id7.pdf") is None


def test_vault_file_name_appends_millisecond_timestamp_on_upload() -> None:
    name = vault_file_name(
        "INV-007",
        7,
        date(2026, 5, 12),
        "scan.pdf",
        unique_timestamp=True,
        timestamp_ms="1712345678901",
    )
    assert name == "INV-007_2026-05-12_id7_1712345678901.pdf"


def test_vault_file_name_same_file_uploaded_twice_gets_unique_names(
    monkeypatch,
) -> None:
    stamps = iter(["1712345678901", "1712345678999"])
    monkeypatch.setattr(
        "app.services.vault.vault_paths.upload_timestamp_ms",
        lambda: next(stamps),
    )
    first = vault_file_name(
        "INV-007", 11, date(2026, 5, 12), "scan.pdf", unique_timestamp=True
    )
    second = vault_file_name(
        "INV-007", 12, date(2026, 5, 12), "scan.pdf", unique_timestamp=True
    )
    assert first == "INV-007_2026-05-12_id11_1712345678901.pdf"
    assert second == "INV-007_2026-05-12_id12_1712345678999.pdf"
    assert first != second


def test_vault_file_name_preserves_timestamp_when_relocating() -> None:
    stored = "INV-007_2026-05-12_id7_1712345678901.pdf"
    assert (
        vault_file_name("INV-007", 7, date(2026, 5, 12), stored)
        == stored
    )


def test_build_vault_blob_name_unique_timestamp_on_upload() -> None:
    path = build_vault_blob_name(
        _TID,
        "hv-org",
        tenant_name="HV Org",
        route_target=ROUTE_PURCHASE,
        vendor_name="James Patel Consulting",
        storage_vendor_slug="james-patel",
        invoice_id=7,
        invoice_no="INV-007",
        invoice_date=date(2026, 5, 12),
        original_filename="scan.pdf",
        unique_timestamp=True,
        timestamp_ms="1712345678901",
    )
    assert path.endswith(
        "INV-007_2026-05-12_id7_1712345678901.pdf"
    )


def test_strip_org_segment_from_blob_path() -> None:
    legacy = (
        f"{_PREFIX}invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-007_2026-05-12_id7.pdf"
    )
    flat = (
        f"{_PREFIX}invoice/Purchase Management/Vendor/2026/May/INV-007_2026-05-12_id7.pdf"
    )
    assert strip_org_segment_from_blob_path(legacy) == flat
    assert strip_org_segment_from_blob_path(flat) is None
    assert (
        insert_org_segment_into_blob_path(flat, "HvOrg")
        == legacy
    )


def test_filename_from_stored_vault_path() -> None:
    assert (
        filename_from_stored(
            "azureblob://invoices/invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-007_2026-05-12_id7.pdf"
        )
        == "INV-007_2026-05-12_id7.pdf"
    )


def test_relocate_paths_unique_for_shared_invoice_no() -> None:
    """Split dossier members must not collide when OCR yields the same invoice_no."""
    shared = "260671582"
    paths = [
        build_vault_blob_name(
            _TID,
            "hv-org",
            invoice_id=invoice_id,
            invoice_no=shared,
            invoice_date=date(2026, 6, 5),
            original_filename="part.pdf",
            route_target=ROUTE_VAULT,
            vendor_name="Spectra Innovations",
            document_type_folder="DT-07 · COO",
        )
        for invoice_id in (21, 22, 23, 24, 25)
    ]
    assert len(set(paths)) == 5
    assert all("_id" in path for path in paths)


def test_build_vault_tree() -> None:
    tree = build_vault_tree(
        [
            {
                "org": "HvOrg",
                "book": "Purchase Management",
                "document_type": "",
                "vendor": "Atlassian Pty Ltd",
                "year": "2026",
                "month": "May",
            },
            {
                "org": "HvOrg",
                "book": "Expenses Management",
                "document_type": "",
                "vendor": "James Patel Consulting",
                "year": "2026",
                "month": "May",
            },
        ]
    )
    assert tree[0]["label"] == "HvOrg"
    assert len(tree[0]["children"]) == 2
    assert tree[0]["children"][0]["kind"] == "book"
    assert tree[0]["children"][0]["children"][0]["kind"] == "vendor"


def test_build_vault_tree_with_document_type() -> None:
    tree = build_vault_tree(
        [
            {
                "org": "HvOrg",
                "book": ROUTE_VAULT,
                "document_type": "DT-13 · Vendor statement",
                "vendor": "Sysco",
                "year": "2026",
                "month": "May",
            },
        ]
    )
    vault_book = tree[0]["children"][0]
    assert vault_book["label"] == ROUTE_VAULT
    assert vault_book["children"][0]["kind"] == "document_type"
    assert vault_book["children"][0]["label"] == "DT-13 · Vendor statement"
    assert vault_book["children"][0]["children"][0]["kind"] == "vendor"
