"""Vault first-paint regressions (perf/vault-optimization)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor_master import VendorMasterRecord
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_VAULT
from app.services.rule_book.rule_book_config_io import clear_posting_config_cache
from app.services.rule_book.rule_book_config_repository import ensure_default_config, upsert_config
from app.tenant_ids import TESTING_TENANT_UUID


def _capture_sql(db_session: AsyncSession):
    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    return statements, lambda: event.remove(
        sync_engine, "before_cursor_execute", _before_cursor_execute
    )


async def _add_vault_file(
    db_session: AsyncSession,
    tmp_path,
    *,
    vendor: str,
    invoice_no: str,
    file_hash: str | None = None,
    route_target: str = ROUTE_PURCHASE,
) -> Invoice:
    pdf_path = tmp_path / f"{invoice_no}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=vendor,
        invoice_no=invoice_no,
        invoice_date=date(2026, 5, 4),
        total=Decimal("100.00"),
        status=InvoiceStatus.PROCESSED,
        raw_file_path=str(pdf_path),
        file_hash=file_hash or uuid4().hex,
        route_target=route_target,
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()
    return inv


@pytest.mark.asyncio
async def test_vault_tree_file_limit_keeps_folder_counts(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    await _add_vault_file(db_session, tmp_path, vendor="Acme", invoice_no="INV-A")
    await _add_vault_file(db_session, tmp_path, vendor="Acme", invoice_no="INV-B")
    await _add_vault_file(db_session, tmp_path, vendor="Beta", invoice_no="INV-C")

    res = await client.get("/api/vault/tree?file_limit=1")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["file_count"] == 3
    assert len(data["files"]) == 1
    assert data["tree"][0]["count"] == 3

    omitted = await client.get("/api/vault/tree?include_files=false")
    assert omitted.status_code == 200
    body = omitted.json()["data"]
    assert body["files"] == []
    assert body["file_count"] == 3
    assert body["tree"][0]["count"] == 3


@pytest.mark.asyncio
async def test_vault_tree_skips_ocr_text_and_master_hydration(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-vault-1",
            name="Vault Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await _add_vault_file(db_session, tmp_path, vendor="Acme", invoice_no="INV-SQL")

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/vault/tree?include_files=false")
    finally:
        stop()

    assert res.status_code == 200
    sql = " ".join(statements).lower()
    assert "document_text" not in sql
    assert "approval_chain" not in sql
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_vault_files_filter_count_is_not_truncated(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    for index in range(3):
        await _add_vault_file(
            db_session,
            tmp_path,
            vendor="Acme Co",
            invoice_no=f"INV-ACME-{index}",
        )
    await _add_vault_file(
        db_session,
        tmp_path,
        vendor="Other Co",
        invoice_no="INV-OTHER",
    )

    res = await client.get("/api/vault/files?vendor=Acme Co&limit=1")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["count"] == 3
    assert len(data["files"]) == 1
    assert data["files"][0]["vendor"] == "Acme Co"


@pytest.mark.asyncio
async def test_rule_book_document_sets_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-vault-sets",
            name="Sets Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=document_sets")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"document_sets"}
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_vault_document_set_counts_are_not_truncated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    raw = dict(await ensure_default_config(db_session, TESTING_TENANT_UUID))
    raw["document_sets"] = [
        {
            "id": "ds-vault-po",
            "pattern": "PO-VAULT",
            "set_name": "Vault POs",
            "isolated": False,
        }
    ]
    await upsert_config(db_session, TESTING_TENANT_UUID, raw, updated_by_user_id=None)
    clear_posting_config_cache()

    for index in range(51):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Set Vendor",
                invoice_no=f"PO-VAULT-{index}",
                invoice_date=date(2026, 5, 4),
                total=Decimal("10.00"),
                status=InvoiceStatus.PROCESSED,
                file_hash=uuid4().hex,
                route_target=ROUTE_VAULT,
                currency="AUD",
            )
        )
    await db_session.flush()

    res = await client.get("/api/vault/document-sets")
    assert res.status_code == 200
    sets = res.json()["data"]["sets"]
    card = next(row for row in sets if row["id"] == "ds-vault-po")
    assert card["match_count"] == 51
    assert len(card["invoices"]) == 50
