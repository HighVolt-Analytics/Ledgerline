"""Personal report column layout API and export slicing."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.report_column_layout import ReportColumnLayout
from app.models.tenant import Tenant
from app.schemas.report_catalog import ReportPreview, ReportPreviewRow
from app.services.reports.report_layout_service import apply_column_layout
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers


def _today() -> date:
    return date.today()


async def _invoice(db: AsyncSession, **kwargs) -> Invoice:
    payload = {
        "tenant_id": TESTING_TENANT_UUID,
        "vendor": "Layout Co",
        "invoice_no": "LAY-1",
        "invoice_date": _today(),
        "due_date": _today() + timedelta(days=14),
        "subtotal": Decimal("100.00"),
        "gst": Decimal("10.00"),
        "total": Decimal("110.00"),
        "currency": "AUD",
        "status": InvoiceStatus.PROCESSED,
        "file_hash": kwargs.pop("file_hash", f"layout-{id(kwargs)}"),
    }
    payload.update(kwargs)
    inv = Invoice(**payload)
    db.add(inv)
    await db.flush()
    return inv


def test_apply_column_layout_permutes_and_drops_stale_keys() -> None:
    preview = ReportPreview(
        report_id="invoice-register",
        title="Invoice Register",
        period_label="2026-08",
        columns=["Vendor", "Invoice No", "Total", "Status"],
        rows=[
            ReportPreviewRow(cells=["Acme", "INV-1", "10.00", "processed"]),
            ReportPreviewRow(cells=["Beta", "INV-2", "20.00", "processed"], emphasize=True),
        ],
    )
    sliced = apply_column_layout(preview, ["Status", "Missing", "Invoice No", "Status"])
    assert sliced.columns == ["Status", "Invoice No"]
    assert sliced.rows[0].cells == ["processed", "INV-1"]
    assert sliced.rows[1].cells == ["processed", "INV-2"]
    assert sliced.rows[1].emphasize is True
    assert sliced.rows[0].cells != preview.rows[0].cells
    fallback = apply_column_layout(preview, ["Not a column"])
    assert fallback.columns == preview.columns
    assert fallback.rows[0].cells == preview.rows[0].cells


def _xlsx_sheet(content: bytes) -> tuple[list[str], list[tuple[str, ...]]]:
    wb = load_workbook(BytesIO(content))
    ws = wb.active
    headers = [
        "" if cell is None else str(cell)
        for cell in next(ws.iter_rows(min_row=4, max_row=4, values_only=True))
    ]
    rows: list[tuple[str, ...]] = []
    for row in ws.iter_rows(min_row=5, values_only=True):
        values = tuple("" if cell is None else str(cell) for cell in row)
        if any(values):
            rows.append(values)
    return headers, rows


@pytest.mark.asyncio
async def test_layout_crud_rename_delete_and_unknown_report(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Vendor focus",
            "column_config": {"columns": ["Vendor", "Invoice No"]},
        },
    )
    assert created.status_code == 200, created.text
    layout = created.json()["data"]
    layout_id = layout["id"]
    assert layout["name"] == "Vendor focus"
    assert layout["is_default"] is False

    listed = await client.get("/api/reports/invoice-register/layouts")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["data"]] == [layout_id]

    renamed = await client.patch(
        f"/api/reports/invoice-register/layouts/{layout_id}",
        json={"name": "AP shortlist"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "AP shortlist"

    dup = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "AP shortlist",
            "column_config": {"columns": ["Vendor"]},
        },
    )
    assert dup.status_code == 422

    missing_report = await client.get("/api/reports/not-a-real-report/layouts")
    assert missing_report.status_code == 404

    deleted = await client.delete(f"/api/reports/invoice-register/layouts/{layout_id}")
    assert deleted.status_code == 200
    empty = await client.get("/api/reports/invoice-register/layouts")
    assert empty.json()["data"] == []
    gone = await client.delete(f"/api/reports/invoice-register/layouts/{layout_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_set_default_layout_demotes_previous(
    client: AsyncClient,
) -> None:
    first = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Layout A",
            "column_config": {"columns": ["Vendor"]},
            "is_default": True,
        },
    )
    assert first.status_code == 200
    a_id = first.json()["data"]["id"]
    assert first.json()["data"]["is_default"] is True

    second = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Layout B",
            "column_config": {"columns": ["Invoice No"]},
        },
    )
    assert second.status_code == 200
    b_id = second.json()["data"]["id"]

    promoted = await client.post(
        f"/api/reports/invoice-register/layouts/{b_id}/default"
    )
    assert promoted.status_code == 200
    assert promoted.json()["data"]["is_default"] is True

    listed = await client.get("/api/reports/invoice-register/layouts")
    by_id = {row["id"]: row for row in listed.json()["data"]}
    assert by_id[a_id]["is_default"] is False
    assert by_id[b_id]["is_default"] is True

    third = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Layout C",
            "column_config": {"columns": ["Status"]},
            "is_default": True,
        },
    )
    assert third.status_code == 200
    c_id = third.json()["data"]["id"]
    listed = await client.get("/api/reports/invoice-register/layouts")
    by_id = {row["id"]: row for row in listed.json()["data"]}
    assert by_id[a_id]["is_default"] is False
    assert by_id[b_id]["is_default"] is False
    assert by_id[c_id]["is_default"] is True


@pytest.mark.asyncio
async def test_layouts_are_personal_and_tenant_isolated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mine = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Mine",
            "column_config": {"columns": ["Vendor"]},
        },
    )
    assert mine.status_code == 200
    mine_id = mine.json()["data"]["id"]

    coworker, coworker_token = await seed_admin_user(
        db_session, email="coworker-layouts@test.example.com"
    )
    await db_session.commit()
    coworker_headers = tenant_auth_headers(coworker_token, TESTING_TENANT_UUID)
    coworker_list = await client.get(
        "/api/reports/invoice-register/layouts", headers=coworker_headers
    )
    assert coworker_list.status_code == 200
    assert coworker_list.json()["data"] == []
    coworker_get = await client.patch(
        f"/api/reports/invoice-register/layouts/{mine_id}",
        json={"name": "Hijacked"},
        headers=coworker_headers,
    )
    assert coworker_get.status_code == 404
    coworker_default = await client.post(
        f"/api/reports/invoice-register/layouts/{mine_id}/default",
        headers=coworker_headers,
    )
    assert coworker_default.status_code == 404
    coworker_delete = await client.delete(
        f"/api/reports/invoice-register/layouts/{mine_id}",
        headers=coworker_headers,
    )
    assert coworker_delete.status_code == 404
    coworker_export = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": mine_id},
        headers=coworker_headers,
    )
    assert coworker_export.status_code == 404
    still_mine = await client.get("/api/reports/invoice-register/layouts")
    assert [row["id"] for row in still_mine.json()["data"]] == [mine_id]

    other_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee2")
    db_session.add(
        Tenant(
            id=other_id,
            name="Other Layout Co",
            slug="other-layout",
            currency="AUD",
            settings_json={"country": "AU"},
        )
    )
    await db_session.flush()
    foreign_user, _ = await seed_admin_user(
        db_session,
        email="foreign-layouts@test.example.com",
        tenant_id=other_id,
        tenant_slug="other-layout",
    )
    db_session.add(
        ReportColumnLayout(
            tenant_id=other_id,
            user_id=foreign_user.id,
            report_id="invoice-register",
            name="FOREIGN-LAYOUT",
            column_config={"columns": ["Vendor"]},
            is_default=True,
        )
    )
    await db_session.commit()

    listed = await client.get("/api/reports/invoice-register/layouts")
    names = [row["name"] for row in listed.json()["data"]]
    assert "Mine" in names
    assert "FOREIGN-LAYOUT" not in names
    assert coworker.id


@pytest.mark.asyncio
async def test_export_layout_id_changes_columns_not_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _invoice(
        db_session,
        file_hash="lay-exp-1",
        vendor="Alpha Co",
        invoice_no="LAY-EXP-1",
        total=Decimal("11.00"),
    )
    await _invoice(
        db_session,
        file_hash="lay-exp-2",
        vendor="Beta Co",
        invoice_no="LAY-EXP-2",
        total=Decimal("22.00"),
    )
    await db_session.commit()

    layout_a = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Export A",
            "column_config": {"columns": ["Vendor", "Invoice No"]},
        },
    )
    layout_b = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Export B",
            "column_config": {"columns": ["Invoice No", "Status"]},
        },
    )
    assert layout_a.status_code == 200
    assert layout_b.status_code == 200
    a_id = layout_a.json()["data"]["id"]
    b_id = layout_b.json()["data"]["id"]

    export_a = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": a_id},
    )
    export_b = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": b_id},
    )
    assert export_a.status_code == 200
    assert export_b.status_code == 200

    headers_a, rows_a = _xlsx_sheet(export_a.content)
    headers_b, rows_b = _xlsx_sheet(export_b.content)
    assert headers_a[:2] == ["Vendor", "Invoice No"]
    assert headers_b[:2] == ["Invoice No", "Status"]
    assert headers_a != headers_b
    assert len(rows_a) == len(rows_b)
    invoices_a = [row[headers_a.index("Invoice No")] for row in rows_a]
    invoices_b = [row[headers_b.index("Invoice No")] for row in rows_b]
    assert invoices_a == invoices_b
    assert "LAY-EXP-1" in invoices_a
    assert "LAY-EXP-2" in invoices_a
    assert "Alpha Co" in [row[headers_a.index("Vendor")] for row in rows_a]
    assert "Status" not in headers_a
    assert "Vendor" not in headers_b

    unknown = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": 999999},
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_export_keeps_layout_columns_when_date_filter_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    old_day = _today() - timedelta(days=120)
    await _invoice(
        db_session,
        file_hash="lay-filter-old",
        vendor="Old Co",
        invoice_no="LAY-OLD",
        invoice_date=old_day,
        due_date=old_day + timedelta(days=14),
    )
    await _invoice(
        db_session,
        file_hash="lay-filter-new",
        vendor="New Co",
        invoice_no="LAY-NEW",
        invoice_date=_today(),
    )
    await db_session.commit()

    layout = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Filter independent",
            "column_config": {"columns": ["Vendor", "Invoice No"]},
        },
    )
    assert layout.status_code == 200
    layout_id = layout.json()["data"]["id"]

    month_export = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": layout_id},
    )
    old_export = await client.post(
        "/api/reports/invoice-register/export",
        json={
            "format": "xlsx",
            "range": "custom",
            "from": old_day.isoformat(),
            "to": old_day.isoformat(),
            "layout_id": layout_id,
        },
    )
    assert month_export.status_code == 200, month_export.text
    assert old_export.status_code == 200, old_export.text

    month_headers, month_rows = _xlsx_sheet(month_export.content)
    old_headers, old_rows = _xlsx_sheet(old_export.content)
    assert month_headers[:2] == ["Vendor", "Invoice No"]
    assert old_headers[:2] == ["Vendor", "Invoice No"]
    month_nos = [row[month_headers.index("Invoice No")] for row in month_rows]
    old_nos = [row[old_headers.index("Invoice No")] for row in old_rows]
    assert "LAY-NEW" in month_nos
    assert "LAY-OLD" in month_nos
    assert old_nos == ["LAY-OLD"]
    assert "Status" not in month_headers
    assert "Status" not in old_headers

    other = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Status only",
            "column_config": {"columns": ["Invoice No", "Status"]},
        },
    )
    other_id = other.json()["data"]["id"]
    other_export = await client.post(
        "/api/reports/invoice-register/export",
        json={
            "format": "xlsx",
            "range": "custom",
            "from": old_day.isoformat(),
            "to": old_day.isoformat(),
            "layout_id": other_id,
        },
    )
    assert other_export.status_code == 200
    other_headers, other_rows = _xlsx_sheet(other_export.content)
    assert other_headers[:2] == ["Invoice No", "Status"]
    assert [row[other_headers.index("Invoice No")] for row in other_rows] == ["LAY-OLD"]
    assert "Vendor" not in other_headers


@pytest.mark.asyncio
async def test_stale_layout_keys_are_dropped_without_rewriting_the_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _invoice(db_session, file_hash="lay-stale-1", invoice_no="LAY-STALE")
    await db_session.commit()

    saved_columns = ["Vendor", "Removed Column", "Invoice No"]
    created = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "Stale mix",
            "column_config": {"columns": saved_columns},
        },
    )
    assert created.status_code == 200
    layout_id = created.json()["data"]["id"]
    assert created.json()["data"]["column_config"]["columns"] == saved_columns

    exported = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": layout_id},
    )
    assert exported.status_code == 200, exported.text
    headers, rows = _xlsx_sheet(exported.content)
    assert headers[:2] == ["Vendor", "Invoice No"]
    assert "Removed Column" not in headers
    assert "LAY-STALE" in [row[headers.index("Invoice No")] for row in rows]

    listed = await client.get("/api/reports/invoice-register/layouts")
    stored = next(row for row in listed.json()["data"] if row["id"] == layout_id)
    assert stored["column_config"]["columns"] == saved_columns

    ghost = await client.post(
        "/api/reports/invoice-register/layouts",
        json={
            "name": "All stale",
            "column_config": {"columns": ["Ghost Col"]},
        },
    )
    assert ghost.status_code == 200
    ghost_id = ghost.json()["data"]["id"]
    ghost_export = await client.post(
        "/api/reports/invoice-register/export",
        json={"format": "xlsx", "range": "month", "layout_id": ghost_id},
    )
    assert ghost_export.status_code == 200
    ghost_headers, _ = _xlsx_sheet(ghost_export.content)
    assert "Vendor" in ghost_headers
    assert "Invoice No" in ghost_headers
    assert "Ghost Col" not in ghost_headers
    still = await client.get("/api/reports/invoice-register/layouts")
    ghost_stored = next(row for row in still.json()["data"] if row["id"] == ghost_id)
    assert ghost_stored["column_config"]["columns"] == ["Ghost Col"]
