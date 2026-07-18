"""Vision can-understand vault sync — type as top-level book, not under Unrouted."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.tenant.tenant_storage_paths import blob_name_from_stored
from app.services.vault.vault_blob_sync import sync_vision_header_vault_path
from app.services.vault.vault_invoice_paths import vault_document_type_folder_for_invoice
from app.services.vault.vault_paths import ROUTE_SALES, ROUTE_UNROUTED
from app.tenant_ids import TESTING_TENANT_UUID


def test_unrouted_with_leftover_dt_code_still_uses_heading() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target=None,
        document_type_code="DT-01",
        document_heading="PACKING LIST",
        extracted_fields={"canonical_document_type": "Packing List"},
    )
    assert vault_document_type_folder_for_invoice(inv, []) == "Packing List"


def test_type_as_book_has_no_nested_type_folder() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        route_target="Packing List",
        document_heading="PACKING LIST",
        extracted_fields={"canonical_document_type": "Packing List"},
    )
    assert vault_document_type_folder_for_invoice(inv, []) is None


def test_sales_with_dt_code_stays_flat() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_SALES,
        document_type_code="DT-10",
        document_heading="PACKING LIST",
        extracted_fields={"canonical_document_type": "Packing List"},
    )
    assert vault_document_type_folder_for_invoice(inv, []) is None


@pytest.mark.asyncio
async def test_sync_vision_moves_out_of_sales_into_type_book(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.shared.blob_storage.is_blob_enabled",
        lambda: False,
    )

    sales_rel = (
        f"{TESTING_TENANT_UUID}/invoice/{ROUTE_SALES}/"
        "Old Vendor/Unknown/Unknown/packing.pdf"
    )
    sales_path = tmp_path / sales_rel
    sales_path.parent.mkdir(parents=True, exist_ok=True)
    sales_path.write_bytes(b"%PDF-1.4 packing")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        raw_file_path=str(sales_path),
        file_hash="vision-vault-sync-hash",
        route_target=ROUTE_SALES,
        document_type_code="DT-99",
        document_heading="PACKING LIST",
        vendor="Acme Supplies",
        extracted_fields={"canonical_document_type": "Packing List"},
        storage_vendor_slug="acme-supplies",
    )
    db_session.add(inv)
    await db_session.flush()

    moved = await sync_vision_header_vault_path(db_session, inv, parsed_vendor=inv.vendor)
    await db_session.flush()

    assert moved is True
    assert inv.route_target == "Packing List"
    assert not sales_path.is_file()
    new_name = (blob_name_from_stored(inv.raw_file_path) or "").replace("\\", "/")
    assert f"/{ROUTE_UNROUTED}/" not in new_name
    assert f"/{ROUTE_SALES}/" not in new_name
    assert "/invoice/Packing List/Acme Supplies/" in new_name
    assert Path(inv.raw_file_path).is_file()
