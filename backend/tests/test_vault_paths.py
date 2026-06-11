"""Tests for vault folder path helpers."""

from datetime import date

from app.services.vault_paths import (
    ROUTE_PURCHASE,
    ROUTE_UNROUTED,
    build_vault_blob_name,
    build_vault_tree,
    filename_from_stored,
    vault_book_folder,
    vault_file_name,
    vault_month,
    vault_org_folder,
    vault_vendor_folder,
)


def test_vault_org_folder() -> None:
    assert vault_org_folder("hv-org") == "HvOrg"


def test_vault_book_folder() -> None:
    assert vault_book_folder(ROUTE_PURCHASE) == "Purchase Management"
    assert vault_book_folder(None) == ROUTE_UNROUTED
    assert vault_book_folder("") == ROUTE_UNROUTED


def test_vault_vendor_folder_display_name() -> None:
    assert vault_vendor_folder("Atlassian Pty Ltd") == "Atlassian Pty Ltd"
    assert vault_vendor_folder(None, "atlassian-pty-ltd") == "Atlassian Pty Ltd"


def test_vault_month_name_only() -> None:
    assert vault_month(date(2026, 5, 4)) == "May"


def test_build_vault_blob_name() -> None:
    path = build_vault_blob_name(
        "hv-org",
        org_name="HV Org",
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
        == "invoice/HvOrg/Purchase Management/James Patel Consulting/2026/May/INV-007_2026-05-12.pdf"
    )


def test_purchase_blob_name_flat_with_shared_po_in_filename() -> None:
    path = build_vault_blob_name(
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
    assert path.endswith("GRN_PO-MKT-2026-014_2026-06-03.pdf")
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
        == "GRN_PO-MKT-2026-014_2026-06-03.pdf"
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
        == "INV_PO-MKT-2026-014_2026-06-05.pdf"
    )


def test_filename_from_stored_vault_path() -> None:
    assert (
        filename_from_stored(
            "azureblob://invoices/invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-007_2026-05-12.pdf"
        )
        == "INV-007_2026-05-12.pdf"
    )


def test_build_vault_tree() -> None:
    tree = build_vault_tree(
        [
            {
                "org": "HvOrg",
                "book": "Purchase Management",
                "vendor": "Atlassian Pty Ltd",
                "year": "2026",
                "month": "May",
            },
            {
                "org": "HvOrg",
                "book": "Expenses Management",
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
