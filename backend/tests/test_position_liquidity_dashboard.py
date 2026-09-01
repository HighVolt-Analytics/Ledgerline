"""Reconciliation tests: Position & Liquidity dashboard === detail report totals."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.journal import EntryType
from app.models.payment import Payment, PaymentStatus
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_TEAM,
)
from app.services.reports.exception_status_catalog_builders import (
    _parse_money,
    _preview_maps,
    build_control_centre,
)
from app.services.reports.payables_catalog_builders import (
    ap_outstanding_rows,
    build_vendor_spend_summary,
)
from app.services.reports.position_liquidity_service import (
    _ap_lines,
    _compute_dpo,
    _on_time_payment_rate,
    _sum_ap_buckets,
    _vendor_concentration,
    ap_outstanding_total_from_aged,
    build_position_liquidity_dashboard,
)
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.statement_builders import _build_aged, _build_budget_variance
from app.services.reports.team_expense_reports_service import build_advance_settlement_rows
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers
from tests.journal_test_helpers import seed_journal_batch

TENANT_A_ID = UUID("11111111-1111-4111-8111-111111111101")
TENANT_B_ID = UUID("11111111-1111-4111-8111-111111111102")
TENANT_HEADER_A_ID = UUID("22222222-2222-4222-8222-222222222201")
TENANT_HEADER_B_ID = UUID("22222222-2222-4222-8222-222222222202")
AP_OUTSTANDING_A = Decimal("100000.00")
AP_OUTSTANDING_B = Decimal("999999.00")


async def _invoice(db: AsyncSession, **kwargs) -> Invoice:
    payload = {
        "tenant_id": TESTING_TENANT_UUID,
        "vendor": "Acme",
        "invoice_no": "PL-INV-1",
        "invoice_date": date.today(),
        "due_date": date.today() + timedelta(days=10),
        "subtotal": Decimal("100.00"),
        "gst": Decimal("10.00"),
        "total": Decimal("110.00"),
        "currency": "AUD",
        "status": InvoiceStatus.PROCESSED,
        "file_hash": kwargs.pop("file_hash", f"pl-{id(kwargs)}"),
    }
    payload.update(kwargs)
    inv = Invoice(**payload)
    db.add(inv)
    await db.flush()
    return inv


async def _journal(
    db: AsyncSession,
    invoice: Invoice,
    *,
    credit: Decimal | None = None,
    debit: Decimal | None = None,
    on: date | None = None,
) -> None:
    dr = Decimal("0") if debit is None else debit
    cr = Decimal("0") if credit is None else credit
    if debit is None and credit is None:
        cr = Decimal("110.00")
    await seed_journal_batch(
        db,
        invoice,
        [
            (
                "2000",
                "Accounts Payable",
                dr,
                cr,
                EntryType.DEBIT if dr else EntryType.CREDIT,
            )
        ],
        entry_date=on or invoice.invoice_date or date.today(),
    )


async def _payment(
    db: AsyncSession,
    invoice: Invoice,
    *,
    amount: Decimal | None = Decimal("110.00"),
    status: PaymentStatus = PaymentStatus.PAID,
    paid_date: date | None = None,
) -> Payment:
    paid = paid_date or date.today()
    row = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        vendor=invoice.vendor,
        amount=amount,
        currency=invoice.currency or "AUD",
        status=status,
        paid_date=datetime.combine(paid, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_position_liquidity_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/position-liquidity")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["kpis"]["ap_outstanding"] == "0.00"
    assert body["meta"]["currency"]


@pytest.mark.asyncio
async def test_ap_outstanding_reconciles_with_aged_payables(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="pl-ap-1",
        invoice_no="PL-AP-1",
        due_date=as_of + timedelta(days=5),
        total=Decimal("200.00"),
        approval_chain={"approvals": [{"name": "Mgr", "at": "2026-01-01T00:00:00Z"}]},
    )
    await _journal(db_session, inv, credit=Decimal("200.00"))
    partial = await _invoice(
        db_session,
        file_hash="pl-ap-2",
        invoice_no="PL-PARTIAL",
        due_date=as_of - timedelta(days=3),
        total=Decimal("100.00"),
    )
    await _journal(db_session, partial, credit=Decimal("100.00"))
    await _journal(db_session, partial, debit=Decimal("40.00"))
    await db_session.commit()

    dashboard = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    aged_total = await ap_outstanding_total_from_aged(
        db_session, TESTING_TENANT_UUID, as_of, base=dashboard.meta.currency
    )
    assert dashboard.kpis.ap_outstanding == aged_total

    lines = await _ap_lines(
        db_session, TESTING_TENANT_UUID, as_of, base=dashboard.meta.currency
    )
    buckets = _sum_ap_buckets(lines, as_of)
    assert dashboard.kpis.ap_outstanding == buckets["ap_outstanding"]
    assert dashboard.kpis.due_next_7_days == buckets["due_7"]
    assert dashboard.kpis.overdue == buckets["overdue"]

    res = await client.get("/api/dashboard/position-liquidity")
    assert Decimal(res.json()["data"]["kpis"]["ap_outstanding"]) == aged_total


@pytest.mark.asyncio
async def test_due_buckets_are_non_overlapping(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    fixtures = [
        ("d7", as_of + timedelta(days=3), Decimal("70.00")),
        ("d14", as_of + timedelta(days=10), Decimal("80.00")),
        ("d30", as_of + timedelta(days=20), Decimal("90.00")),
        ("od", as_of - timedelta(days=2), Decimal("50.00")),
    ]
    for tag, due, amount in fixtures:
        inv = await _invoice(
            db_session,
            file_hash=f"pl-bucket-{tag}",
            invoice_no=f"PL-{tag.upper()}",
            due_date=due,
            total=amount,
        )
        await _journal(db_session, inv, credit=amount)
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.due_next_7_days == Decimal("70.00")
    assert dash.kpis.due_next_14_days == Decimal("80.00")
    assert dash.kpis.due_next_30_days == Decimal("90.00")
    assert dash.kpis.overdue == Decimal("50.00")
    assert (
        dash.kpis.due_next_7_days
        + dash.kpis.due_next_14_days
        + dash.kpis.due_next_30_days
        + dash.kpis.overdue
        <= dash.kpis.ap_outstanding
    )


@pytest.mark.asyncio
async def test_overdue_pct_uses_same_ap_denominator(db_session: AsyncSession) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="pl-od-pct",
        due_date=as_of - timedelta(days=1),
        total=Decimal("25.00"),
    )
    await _journal(db_session, inv, credit=Decimal("25.00"))
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    if dash.kpis.ap_outstanding > 0:
        expected = (
            dash.kpis.overdue / dash.kpis.ap_outstanding * Decimal("100")
        ).quantize(Decimal("0.01"))
        assert dash.kpis.overdue_pct == expected


@pytest.mark.asyncio
async def test_budget_utilisation_reconciles_with_budget_variance(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    preview = await _build_budget_variance(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["budget-variance"],
        start,
        end,
        compare=False,
        as_of=True,
    )
    budget_idx = preview.columns.index("Budget")
    actual_idx = preview.columns.index("Actual")
    allocated = Decimal("0")
    actual = Decimal("0")
    for row in preview.rows:
        if row.emphasize:
            continue
        allocated += _parse_money(row.cells[budget_idx])
        actual += _parse_money(row.cells[actual_idx])
    assert dash.kpis.budget_allocated == allocated
    assert dash.kpis.budget_actual == actual


@pytest.mark.asyncio
async def test_advances_outstanding_reconciles_with_advance_reconciliation(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    rows = await build_advance_settlement_rows(db_session, TESTING_TENANT_UUID)
    expected = sum(
        (Decimal(str(r.advance_ledger_balance or 0)) for r in rows), Decimal("0")
    )
    assert dash.kpis.advances_outstanding == expected


@pytest.mark.asyncio
async def test_open_exceptions_reconciles_with_control_centre(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    preview = await build_control_centre(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["control-centre"],
        start,
        end,
        as_of=True,
    )
    items = _preview_maps(preview)
    assert dash.kpis.open_exceptions_count == len(items)


@pytest.mark.asyncio
async def test_claims_pending_counts_outstanding_approval_chain(
    db_session: AsyncSession,
) -> None:
    pending = await _invoice(
        db_session,
        file_hash="pl-claim-pending",
        route_target=ROUTE_TEAM,
        team_expense_kind="claim",
        evaluation_status=EVAL_PENDING_APPROVAL,
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("55.00"),
        approval_chain={
            "module": "team_expenses",
            "mode": "two_way",
            "required": 2,
            "approvals": [{"user_id": 1, "name": "Mgr"}],
        },
    )
    done = await _invoice(
        db_session,
        file_hash="pl-claim-done",
        route_target=ROUTE_TEAM,
        team_expense_kind="claim",
        evaluation_status=EVAL_PENDING_APPROVAL,
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("99.00"),
        approval_chain={
            "module": "team_expenses",
            "mode": "one_way",
            "required": 1,
            "approvals": [{"user_id": 1, "name": "Mgr"}],
        },
    )
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.claims_pending_count == 1
    assert dash.kpis.claims_pending_value == Decimal("55.00")
    assert pending.id is not None
    assert done.id is not None


@pytest.mark.asyncio
async def test_partial_payment_uses_netted_balance_not_invoice_total(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="pl-partial",
        invoice_no="PL-PARTIAL",
        due_date=as_of + timedelta(days=4),
        total=Decimal("110.00"),
    )
    await _journal(db_session, inv, credit=Decimal("110.00"))
    await _journal(db_session, inv, debit=Decimal("40.00"))
    await db_session.commit()

    rows = await ap_outstanding_rows(db_session, TESTING_TENANT_UUID, as_of)
    partial = next(r for r in rows if r.invoice_no == "PL-PARTIAL")
    assert partial.remaining == Decimal("70.00")

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.due_next_7_days == Decimal("70.00")
    assert dash.kpis.ap_outstanding == Decimal("70.00")


@pytest.mark.asyncio
async def test_dpo_known_inputs_formula(db_session: AsyncSession) -> None:
    """DPO = (avg start/end AP balance ÷ purchases) × days — unit test with fixed window."""
    start = date(2026, 8, 1)
    end = date(2026, 8, 10)
    inv = await _invoice(
        db_session,
        file_hash="pl-dpo",
        invoice_no="PL-DPO",
        invoice_date=start + timedelta(days=2),
        total=Decimal("200.00"),
    )
    await _journal(db_session, inv, credit=Decimal("200.00"), on=start + timedelta(days=2))
    await db_session.commit()

    dpo = await _compute_dpo(
        db_session, TESTING_TENANT_UUID, start, end, base="AUD"
    )
    assert dpo is not None
    # AP at start = 0, at end = 200; purchases in window = 200; days = 10
    expected = (Decimal("100") / Decimal("200") * Decimal("10")).quantize(Decimal("0.01"))
    assert dpo == expected


@pytest.mark.asyncio
async def test_on_time_payment_rate_value_weighted(db_session: AsyncSession) -> None:
    start = date.today() - timedelta(days=30)
    end = date.today()
    on_time_inv = await _invoice(
        db_session,
        file_hash="pl-ontime",
        invoice_no="PL-ON-TIME",
        due_date=end,
        total=Decimal("100.00"),
    )
    late_inv = await _invoice(
        db_session,
        file_hash="pl-late",
        invoice_no="PL-LATE",
        due_date=start,
        total=Decimal("100.00"),
    )
    await _payment(db_session, on_time_inv, amount=Decimal("100.00"), paid_date=end)
    await _payment(db_session, late_inv, amount=Decimal("100.00"), paid_date=end)
    await db_session.commit()

    rate = await _on_time_payment_rate(
        db_session, TESTING_TENANT_UUID, start, end, base="AUD"
    )
    assert rate == Decimal("50.00")


@pytest.mark.asyncio
async def test_discount_capture_honest_gap_not_computed(db_session: AsyncSession) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.discount_capture_rate_pct is None
    assert any("discount" in note.lower() for note in dash.meta.notes)
    assert any("discount_capture" in gap for gap in dash.meta.coverage_gaps)


@pytest.mark.asyncio
async def test_vendor_concentration_reconciles_with_vendor_spend_summary(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    big = await _invoice(
        db_session,
        file_hash="pl-vc-big",
        vendor="Big Vendor Co",
        invoice_no="PL-BIG",
        total=Decimal("800.00"),
    )
    small = await _invoice(
        db_session,
        file_hash="pl-vc-small",
        vendor="Small Vendor Co",
        invoice_no="PL-SMALL",
        total=Decimal("200.00"),
    )
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    top10, _ = await _vendor_concentration(
        db_session, TESTING_TENANT_UUID, start, end, base=dash.meta.currency
    )
    preview = await build_vendor_spend_summary(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["vendor-spend-summary"],
        start,
        end,
        as_of=True,
    )
    invoiced_idx = preview.columns.index("Total Invoiced")
    spends = [
        _parse_money(row.cells[invoiced_idx])
        for row in preview.rows
        if not row.emphasize and row.cells[0].upper() != "TOTAL"
    ]
    total = sum(spends, Decimal("0"))
    manual_top10 = sum(sorted(spends, reverse=True)[:10], Decimal("0"))
    manual_pct = (manual_top10 / total * Decimal("100")).quantize(Decimal("0.01"))
    assert dash.kpis.vendor_top10_concentration_pct == manual_pct
    assert dash.kpis.vendor_top10_concentration_pct == top10
    assert big.vendor in {row.cells[0] for row in preview.rows if not row.emphasize}


@pytest.mark.asyncio
async def test_vendor_concentration_uses_invoiced_not_paid_amount(
    db_session: AsyncSession,
) -> None:
    """Bug #2 guard: concentration ranks on Total Invoiced, not Total Paid."""
    inv = await _invoice(
        db_session,
        file_hash="pl-vc-zero-paid",
        vendor="Zero Paid Co",
        invoice_no="PL-ZERO-PAID",
        total=Decimal("500.00"),
    )
    await _payment(db_session, inv, amount=Decimal("0.00"))
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    preview = await build_vendor_spend_summary(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["vendor-spend-summary"],
        date.fromisoformat(dash.meta.period_start),
        date.fromisoformat(dash.meta.period_end),
        as_of=True,
    )
    paid_idx = preview.columns.index("Total Paid")
    invoiced_idx = preview.columns.index("Total Invoiced")
    row = next(
        r for r in preview.rows if not r.emphasize and r.cells[0] == "Zero Paid Co"
    )
    assert row.cells[paid_idx] == "-"
    assert row.cells[invoiced_idx] == "500.00"
    assert dash.kpis.vendor_top10_concentration_pct == Decimal("100.00")


def test_paid_payment_amount_null_is_zero_not_invoice_total() -> None:
    from types import SimpleNamespace

    from app.services.reports.payables_catalog_builders import _paid_payment_amount

    amount, missing = _paid_payment_amount(
        SimpleNamespace(status=PaymentStatus.PAID, amount=None)
    )
    assert amount == Decimal("0.00")
    assert missing is True


@pytest.mark.asyncio
async def test_open_exceptions_documents_bank_detail_gap(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    gaps = " ".join(dash.meta.coverage_gaps).lower()
    assert "bank_detail_change_before_payment" in gaps
    assert "excluded" in gaps or "omits" in gaps


def _iter_leaf_values(obj: Any) -> Iterator[Any]:
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_leaf_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_leaf_values(value)
    else:
        yield obj


def _response_contains_decimal(body: dict[str, Any], amount: Decimal) -> bool:
    needles = {str(amount), f"{amount:.2f}"}
    return any(str(value) in needles for value in _iter_leaf_values(body))


async def _create_tenant(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    slug: str,
    name: str,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        currency="AUD",
        is_active=True,
    )
    db.add(tenant)
    await db.flush()
    return tenant


async def _seed_tenant_ap(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    amount: Decimal,
    invoice_no: str,
) -> Invoice:
    inv = Invoice(
        tenant_id=tenant_id,
        vendor="Isolation Vendor",
        invoice_no=invoice_no,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=10),
        subtotal=amount,
        gst=Decimal("0"),
        total=amount,
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash=f"iso-ap-{tenant_id}-{invoice_no}",
        approval_chain={"approvals": [{"name": "Mgr", "at": "2026-01-01T00:00:00Z"}]},
    )
    db.add(inv)
    await db.flush()
    await seed_journal_batch(
        db,
        inv,
        [
            (
                "2000",
                "Accounts Payable",
                Decimal("0"),
                amount,
                EntryType.CREDIT,
            )
        ],
        entry_date=inv.invoice_date or date.today(),
    )
    return inv


@pytest.mark.asyncio
async def test_position_liquidity_does_not_leak_across_tenants(
    anon_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/dashboard/position-liquidity scopes every KPI to the auth tenant only."""
    await _create_tenant(
        db_session,
        tenant_id=TENANT_A_ID,
        slug="pl-iso-tenant-a",
        name="PL Iso Tenant A",
    )
    await _create_tenant(
        db_session,
        tenant_id=TENANT_B_ID,
        slug="pl-iso-tenant-b",
        name="PL Iso Tenant B",
    )
    await _seed_tenant_ap(
        db_session,
        tenant_id=TENANT_A_ID,
        amount=AP_OUTSTANDING_A,
        invoice_no="ISO-A-AP",
    )
    await _seed_tenant_ap(
        db_session,
        tenant_id=TENANT_B_ID,
        amount=AP_OUTSTANDING_B,
        invoice_no="ISO-B-AP",
    )
    _user_a, token_a = await seed_admin_user(
        db_session,
        email="pl-iso-a@test.example.com",
        tenant_id=TENANT_A_ID,
        tenant_slug="pl-iso-tenant-a",
    )
    _user_b, token_b = await seed_admin_user(
        db_session,
        email="pl-iso-b@test.example.com",
        tenant_id=TENANT_B_ID,
        tenant_slug="pl-iso-tenant-b",
    )
    await db_session.commit()

    res_a = await anon_client.get(
        "/api/dashboard/position-liquidity",
        headers=tenant_auth_headers(token_a, TENANT_A_ID),
    )
    assert res_a.status_code == 200, res_a.text
    body_a = res_a.json()["data"]
    assert body_a["kpis"]["ap_outstanding"] == str(AP_OUTSTANDING_A)
    assert not _response_contains_decimal(body_a, AP_OUTSTANDING_B)

    res_b = await anon_client.get(
        "/api/dashboard/position-liquidity",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_b.status_code == 200, res_b.text
    body_b = res_b.json()["data"]
    assert body_b["kpis"]["ap_outstanding"] == str(AP_OUTSTANDING_B)
    assert not _response_contains_decimal(body_b, AP_OUTSTANDING_A)


@pytest.mark.asyncio
async def test_position_liquidity_rejects_x_tenant_id_header_mismatch(
    anon_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    await _create_tenant(
        db_session,
        tenant_id=TENANT_HEADER_A_ID,
        slug="pl-iso-header-a",
        name="PL Header Tenant A",
    )
    await _create_tenant(
        db_session,
        tenant_id=TENANT_HEADER_B_ID,
        slug="pl-iso-header-b",
        name="PL Header Tenant B",
    )
    _user_a, token_a = await seed_admin_user(
        db_session,
        email="pl-iso-header-a@test.example.com",
        tenant_id=TENANT_HEADER_A_ID,
        tenant_slug="pl-iso-header-a",
    )
    await db_session.commit()

    res = await anon_client.get(
        "/api/dashboard/position-liquidity",
        headers=tenant_auth_headers(token_a, TENANT_HEADER_B_ID),
    )
    assert res.status_code == 403
