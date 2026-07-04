"""Repair stale raw_file_path after blob relocation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenant_ids import TESTING_TENANT_UUID

from app.models.invoice import Invoice, InvoiceStatus
from app.services.shared.blob_storage import _blob_name_matches_invoice, find_blob_uri_for_invoice
from app.services.shared.file_storage import repair_invoice_stored_path, stored_file_available


def test_blob_name_matches_invoice_marker() -> None:
    assert _blob_name_matches_invoice(
        "invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-104_2026-05-16.pdf",
        104,
    )
    assert _blob_name_matches_invoice(
        "invoice/HvOrg/Vault/DT-07 · coo/Vendor/2026/June/260671582_2026-06-05_id21.pdf",
        21,
    )
    assert not _blob_name_matches_invoice(
        "invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-1040_2026-05-16.pdf",
        104,
    )
    assert not _blob_name_matches_invoice(
        "invoice/HvOrg/Vault/DT-07 · coo/Vendor/2026/June/260671582_2026-06-05_id22.pdf",
        21,
    )


@pytest.mark.asyncio
async def test_repair_invoice_stored_path_from_blob_search(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="abc",
        raw_file_path="azureblob://invoices/invoice/HvOrg/Unrouted/Unknown/Unknown/Unknown/INV-104_undated.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    repaired_uri = (
        "azureblob://invoices/invoice/HvOrg/Purchase Management/Vendor/2026/May/INV-104_2026-05-16.pdf"
    )

    with (
        patch(
            "app.services.file_storage.stored_file_available",
            side_effect=lambda path, **kwargs: path == repaired_uri,
        ),
        patch(
            "app.services.blob_storage.find_blob_uri_for_invoice",
            return_value=repaired_uri,
        ),
    ):
        repaired = await repair_invoice_stored_path(db_session, inv)

    assert repaired is True
    assert inv.raw_file_path == repaired_uri


@pytest.mark.asyncio
async def test_repair_invoice_stored_path_from_audit(
    db_session: AsyncSession,
) -> None:
    from app.models.audit import AuditLog

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="abc",
        raw_file_path="azureblob://invoices/invoice/old.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    repaired_uri = "azureblob://invoices/invoice/new.pdf"
    db_session.add(
        AuditLog(
            invoice_id=inv.id,
            event="blob_relocated",
            detail={"to_path": repaired_uri},
        )
    )
    await db_session.flush()

    with patch(
        "app.services.file_storage._resolve_readable_stored",
        side_effect=lambda stored, **kwargs: repaired_uri if stored == repaired_uri else None,
    ):
        repaired = await repair_invoice_stored_path(db_session, inv)

    assert repaired is True
    assert inv.raw_file_path == repaired_uri
