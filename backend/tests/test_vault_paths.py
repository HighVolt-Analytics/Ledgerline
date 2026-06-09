"""Tests for vault folder path helpers."""

from datetime import date

from app.services.vault_paths import (
    build_vault_blob_name,
    build_vault_tree,
    filename_from_stored,
    vault_month,
    vault_org_folder,
    vault_vendor_folder,
)


def test_vault_org_folder() -> None:
    assert vault_org_folder("hv-org") == "HvOrg"


def test_vault_vendor_folder_display_name() -> None:
    assert vault_vendor_folder("Atlassian Pty Ltd") == "Atlassian Pty Ltd"
    assert vault_vendor_folder(None, "atlassian-pty-ltd") == "Atlassian Pty Ltd"


def test_vault_month_name_only() -> None:
    assert vault_month(date(2026, 5, 4)) == "May"


def test_build_vault_blob_name() -> None:
    path = build_vault_blob_name(
        "hv-org",
        org_name="HV Org",
        vendor_name="James Patel Consulting",
        storage_vendor_slug="james-patel",
        invoice_id=7,
        invoice_no="INV-007",
        invoice_date=date(2026, 5, 12),
        original_filename="scan.pdf",
    )
    assert path == "invoice/HvOrg/James Patel Consulting/2026/May/INV-007_2026-05-12.pdf"


def test_filename_from_stored_vault_path() -> None:
    assert (
        filename_from_stored(
            "azureblob://invoices/invoice/HvOrg/Vendor/2026/May/INV-007_2026-05-12.pdf"
        )
        == "INV-007_2026-05-12.pdf"
    )


def test_build_vault_tree() -> None:
    tree = build_vault_tree(
        [
            {
                "org": "HvOrg",
                "vendor": "Atlassian Pty Ltd",
                "year": "2026",
                "month": "May",
            },
            {
                "org": "HvOrg",
                "vendor": "James Patel Consulting",
                "year": "2026",
                "month": "May",
            },
        ]
    )
    assert tree[0]["label"] == "HvOrg"
    assert len(tree[0]["children"]) == 2
    assert tree[0]["children"][0]["kind"] == "vendor"
