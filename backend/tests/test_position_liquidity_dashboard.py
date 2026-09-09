"""Position & Liquidity dashboard — new report-sourced KPI definitions."""

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
from app.models.journal import EntryType
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_TEAM,
)
from app.services.reports.exception_status_catalog_builders import (
    _parse_money,
    _preview_maps,
    build_claim_status,
    build_invoice_exception,
)
from app.services.reports.position_liquidity_service import (
    _compute_dpo,
    _on_time_payment_rate,
    _vendor_concentration,
    build_position_liquidity_dashboard,
)
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.statement_builders import _build_aged, _build_budget_variance
from app.services.reports.team_expense_catalog_builders import build_advance_aging
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers
from tests.journal_test_helpers import seed_journal_batch

TENANT_A_ID = UUID("11111111-1111-4111-8111-111111111101")
TENANT_B_ID = UUID("11111111-1111-4111-8111-111111111102")
TENANT_HEADER_A_ID = UUID("22222222-2222-4222-8222-222222222201")
TENANT_HEADER_B_ID = UUID("22222222-2222-4222-8222-222222222202")
AP_OUTSTANDING_A = Decimal("100000.00")
AP_OUTSTANDING_B = Decimal("999999.00")


def _ccy_amount(rows, currency: str = "AUD") -> Decimal:
    for row in rows:
        if row.currency == currency:
            return Decimal(str(row.amount))
    return Decimal("0.00")


def _ccy_api(rows: list[dict[str, Any]], currency: str = "AUD") -> Decimal:
    for row in rows:
        if row.get("currency") == currency:
            return Decimal(str(row.get("amount", "0")))
    return Decimal("0.00")


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
    assert body["kpis"]["ap_outstanding_by_currency"] == []
    assert body["kpis"]["due_next_7_days_by_currency"] == []
    assert body["kpis"]["overdue"] == "0.00"
    assert body["meta"]["currency"]


@pytest.mark.asyncio
async def test_ap_outstanding_sums_unpaid_register_totals_per_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    as_of = date.today()
    await _invoice(
        db_session,
        file_hash="pl-ap-aud",
        invoice_no="PL-AP-AUD",
        due_date=as_of + timedelta(days=5),
        total=Decimal("200.00"),
        currency="AUD",
    )
    await _invoice(
        db_session,
        file_hash="pl-ap-inr",
        invoice_no="PL-AP-INR",
        due_date=as_of + timedelta(days=5),
        total=Decimal("500.00"),
        currency="INR",
    )
    paid = await _invoice(
        db_session,
        file_hash="pl-ap-paid",
        invoice_no="PL-AP-PAID",
        due_date=as_of + timedelta(days=5),
        total=Decimal("999.00"),
        currency="AUD",
    )
    await _payment(db_session, paid, amount=Decimal("999.00"), paid_date=as_of)
    await db_session.commit()

    dashboard = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert _ccy_amount(dashboard.kpis.ap_outstanding_by_currency, "AUD") == Decimal(
        "200.00"
    )
    assert _ccy_amount(dashboard.kpis.ap_outstanding_by_currency, "INR") == Decimal(
        "500.00"
    )

    res = await client.get("/api/dashboard/position-liquidity")
    body = res.json()["data"]["kpis"]
    assert _ccy_api(body["ap_outstanding_by_currency"], "AUD") == Decimal("200.00")
    assert _ccy_api(body["ap_outstanding_by_currency"], "INR") == Decimal("500.00")


@pytest.mark.asyncio
async def test_due_next_7_days_window_excludes_overdue_and_beyond(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    fixtures = [
        ("today", as_of, Decimal("10.00")),
        ("d7", as_of + timedelta(days=7), Decimal("70.00")),
        ("d8", as_of + timedelta(days=8), Decimal("80.00")),
        ("od", as_of - timedelta(days=1), Decimal("50.00")),
        ("none", None, Decimal("40.00")),
    ]
    for tag, due, amount in fixtures:
        await _invoice(
            db_session,
            file_hash=f"pl-due-{tag}",
            invoice_no=f"PL-DUE-{tag.upper()}",
            due_date=due,
            total=amount,
            currency="AUD",
        )
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert _ccy_amount(dash.kpis.due_next_7_days_by_currency) == Decimal("80.00")
    assert _ccy_amount(dash.kpis.ap_outstanding_by_currency) == Decimal("250.00")


@pytest.mark.asyncio
async def test_overdue_uses_aged_payables_buckets_not_register(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    # Register unpaid (no payment) — not used for overdue tile
    await _invoice(
        db_session,
        file_hash="pl-od-reg",
        invoice_no="PL-OD-REG",
        due_date=as_of - timedelta(days=10),
        total=Decimal("999.00"),
        currency="AUD",
        status=InvoiceStatus.PENDING,
    )
    # Aged Payables needs PROCESSED + journal remaining
    aged = await _invoice(
        db_session,
        file_hash="pl-od-aged",
        invoice_no="PL-OD-AGED",
        due_date=as_of - timedelta(days=10),
        total=Decimal("100.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
    )
    await _journal(db_session, aged, credit=Decimal("100.00"))
    edge30 = await _invoice(
        db_session,
        file_hash="pl-od-30",
        invoice_no="PL-OD-30",
        due_date=as_of - timedelta(days=30),
        total=Decimal("30.00"),
        status=InvoiceStatus.PROCESSED,
    )
    await _journal(db_session, edge30, credit=Decimal("30.00"))
    edge31 = await _invoice(
        db_session,
        file_hash="pl-od-31",
        invoice_no="PL-OD-31",
        due_date=as_of - timedelta(days=31),
        total=Decimal("31.00"),
        status=InvoiceStatus.PROCESSED,
    )
    await _journal(db_session, edge31, credit=Decimal("31.00"))
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.overdue_1_30 == Decimal("130.00")
    assert dash.kpis.overdue_31_60 == Decimal("31.00")
    assert dash.kpis.overdue == Decimal("161.00")
    assert "overdue_pct" not in dash.kpis.model_dump()

    preview = await _build_aged(
        db_session, TESTING_TENANT_UUID, CATALOG_BY_ID["aged-payables"], as_of
    )
    idx_130 = preview.columns.index("1–30")
    idx_3160 = preview.columns.index("31–60")
    manual_130 = sum(
        (_parse_money(r.cells[idx_130]) for r in preview.rows if not r.emphasize),
        Decimal("0"),
    )
    manual_3160 = sum(
        (_parse_money(r.cells[idx_3160]) for r in preview.rows if not r.emphasize),
        Decimal("0"),
    )
    assert dash.kpis.overdue_1_30 == manual_130
    assert dash.kpis.overdue_31_60 == manual_3160


@pytest.mark.asyncio
async def test_approved_awaiting_uses_uploads_approved_and_awaiting_payment(
    db_session: AsyncSession,
) -> None:
    """Action=Approved (board) + Payment Auth=Awaiting Payment → sum Amount; queue = count."""
    from app.services.approval.approval_board_service import approval_board_column
    from app.services.reports.matrix_service import derive_matrix_payment_status

    # PROCESSED + due date → board Approved + Payment Auth Awaiting Payment
    match = await _invoice(
        db_session,
        file_hash="pl-appr-await",
        invoice_no="PL-APPR-AWAIT",
        due_date=date.today() + timedelta(days=3),
        total=Decimal("1200.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
    )
    # EXCEPTION On Hold (excluded)
    await _invoice(
        db_session,
        file_hash="pl-appr-hold",
        invoice_no="PL-APPR-HOLD",
        total=Decimal("500.00"),
        currency="AUD",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_vaulted",
        document_type_code="INV",
    )
    await db_session.commit()

    assert approval_board_column(match) == "approved"
    assert derive_matrix_payment_status(match, None) == "Awaiting Payment"

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert _ccy_amount(dash.kpis.approved_not_paid_by_currency, "AUD") >= Decimal(
        "1200.00"
    )
    assert dash.kpis.payments_queue_count >= 1


@pytest.mark.asyncio
async def test_budget_utilisation_is_average_of_utilise_pct(
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
    utilise_idx = preview.columns.index("% Utilise")
    values: list[Decimal] = []
    for row in preview.rows:
        if row.emphasize:
            continue
        raw = (row.cells[utilise_idx] or "").strip()
        if not raw or raw == "-":
            continue
        if raw.endswith("%"):
            raw = raw[:-1].strip()
        values.append(Decimal(raw))
    if not values:
        assert dash.kpis.budget_utilisation_pct is None
    else:
        expected = (sum(values) / Decimal(len(values))).quantize(Decimal("0.01"))
        assert dash.kpis.budget_utilisation_pct == expected


@pytest.mark.asyncio
async def test_advances_outstanding_sums_aging_outstanding(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    as_of = date.fromisoformat(dash.meta.as_of)
    aging, _ = await build_advance_aging(
        db_session, TESTING_TENANT_UUID, CATALOG_BY_ID["advance-aging"], as_of
    )
    expected = sum(
        (_parse_money(item.get("Outstanding", "") or "") for item in _preview_maps(aging)),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    assert dash.kpis.advances_outstanding == expected
    assert not hasattr(dash.kpis, "advances_overdue")


@pytest.mark.asyncio
async def test_open_exceptions_counts_invoice_exception_only(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    preview = await build_invoice_exception(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["invoice-exception"],
        start,
        end,
    )
    assert dash.kpis.open_exceptions_count == len(_preview_maps(preview))
    assert not hasattr(dash.kpis, "open_exceptions_at_risk")


@pytest.mark.asyncio
async def test_claims_pending_excludes_only_approved_status_reason(
    db_session: AsyncSession,
) -> None:
    await _invoice(
        db_session,
        file_hash="pl-claim-pending",
        route_target=ROUTE_TEAM,
        team_expense_kind="claim",
        evaluation_status=EVAL_PENDING_APPROVAL,
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("55.00"),
        invoice_date=date.today(),
    )
    await _invoice(
        db_session,
        file_hash="pl-claim-approved",
        route_target=ROUTE_TEAM,
        team_expense_kind="claim",
        status=InvoiceStatus.PROCESSED,
        total=Decimal("99.00"),
        invoice_date=date.today(),
    )
    await _invoice(
        db_session,
        file_hash="pl-claim-rejected",
        route_target=ROUTE_TEAM,
        team_expense_kind="claim",
        status=InvoiceStatus.REJECTED,
        total=Decimal("40.00"),
        invoice_date=date.today(),
    )
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    preview = await build_claim_status(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["claim-status"],
        start,
        end,
        as_of=True,
    )
    expected = sum(
        1
        for item in _preview_maps(preview)
        if (item.get("Status / Reason") or "").strip() != "Approved"
    )
    assert dash.kpis.claims_pending_count == expected
    assert expected >= 2  # pending + rejected at minimum


@pytest.mark.asyncio
async def test_documents_pipeline_is_to_review_only(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.documents_to_review_count >= 0
    assert not hasattr(dash.kpis, "documents_processing_count")


@pytest.mark.asyncio
async def test_partial_payment_with_paid_date_excludes_from_register_ap(
    db_session: AsyncSession,
) -> None:
    """Register unpaid = Payment Date empty; any paid_date drops the invoice from #1."""
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="pl-partial",
        invoice_no="PL-PARTIAL",
        due_date=as_of + timedelta(days=4),
        total=Decimal("110.00"),
    )
    await _payment(db_session, inv, amount=Decimal("40.00"), paid_date=as_of)
    await db_session.commit()

    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert _ccy_amount(dash.kpis.ap_outstanding_by_currency) == Decimal("0.00")
    assert _ccy_amount(dash.kpis.due_next_7_days_by_currency) == Decimal("0.00")


@pytest.mark.asyncio
async def test_dpo_known_inputs_formula(db_session: AsyncSession) -> None:
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
    from app.services.reports.payables_catalog_builders import build_vendor_spend_summary

    await _invoice(
        db_session,
        file_hash="pl-vc-big",
        vendor="Big Vendor Co",
        invoice_no="PL-BIG",
        total=Decimal("800.00"),
    )
    await _invoice(
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


@pytest.mark.asyncio
async def test_notes_document_register_vs_aged_divergence(
    db_session: AsyncSession,
) -> None:
    dash = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    notes = " ".join(dash.meta.notes).lower()
    assert "need not reconcile" in notes or "aged payables" in notes
    assert "no fx" in notes or "per-currency" in notes


def test_paid_payment_amount_null_is_zero_not_invoice_total() -> None:
    from types import SimpleNamespace

    from app.services.reports.payables_catalog_builders import _paid_payment_amount

    amount, missing = _paid_payment_amount(
        SimpleNamespace(status=PaymentStatus.PAID, amount=None)
    )
    assert amount == Decimal("0.00")
    assert missing is True


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
    return inv


@pytest.mark.asyncio
async def test_position_liquidity_does_not_leak_across_tenants(
    anon_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
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
    assert _ccy_api(body_a["kpis"]["ap_outstanding_by_currency"]) == AP_OUTSTANDING_A
    assert not _response_contains_decimal(body_a, AP_OUTSTANDING_B)

    res_b = await anon_client.get(
        "/api/dashboard/position-liquidity",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_b.status_code == 200, res_b.text
    body_b = res_b.json()["data"]
    assert _ccy_api(body_b["kpis"]["ap_outstanding_by_currency"]) == AP_OUTSTANDING_B
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


@pytest.mark.asyncio
async def test_position_liquidity_period_mtd(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/position-liquidity", params={"period": "mtd"})
    assert res.status_code == 200
    meta = res.json()["data"]["meta"]
    today = date.today()
    assert meta["period_start"] == date(today.year, today.month, 1).isoformat()
    assert meta["period_end"] == today.isoformat()
    assert meta["period_label"] == f"{today.strftime('%b')} {today.year} MTD"


@pytest.mark.asyncio
async def test_position_liquidity_period_invalid_defaults_to_fy_ytd(client: AsyncClient) -> None:
    fy = await client.get("/api/dashboard/position-liquidity", params={"period": "fy_ytd"})
    bad = await client.get("/api/dashboard/position-liquidity", params={"period": "not-a-period"})
    assert fy.status_code == 200
    assert bad.status_code == 200
    assert bad.json()["data"]["meta"]["period_label"] == fy.json()["data"]["meta"]["period_label"]
