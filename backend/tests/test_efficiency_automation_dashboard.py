"""Reconciliation tests: Efficiency & Automation dashboard === detail report totals."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_sync_job import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    AccountingSyncJob,
)
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.reports.cfo_efficiency_assumptions import (
    FTE_HOURS_PER_YEAR,
    MANUAL_COST_PER_INVOICE_BASELINE,
    MANUAL_PROCESSING_MINUTES_BASELINE,
)
from app.services.reports.efficiency_automation_service import (
    build_efficiency_automation_dashboard,
    missing_documents_count_from_report,
    touchless_pct_from_process_efficiency,
)
from app.services.reports.exception_status_catalog_builders import (
    process_efficiency_slice,
)
from app.services.reports.position_liquidity_service import build_position_liquidity_dashboard
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers

TENANT_A_ID = UUID("33333333-3333-4333-8333-333333333301")
TENANT_B_ID = UUID("33333333-3333-4333-8333-333333333302")


async def _invoice(db: AsyncSession, **kwargs) -> Invoice:
    payload = {
        "tenant_id": TESTING_TENANT_UUID,
        "vendor": "Eff Vendor",
        "invoice_no": "EA-1",
        "invoice_date": date.today(),
        "due_date": date.today() + timedelta(days=10),
        "subtotal": Decimal("100.00"),
        "gst": Decimal("0"),
        "total": Decimal("100.00"),
        "currency": "AUD",
        "status": InvoiceStatus.PROCESSED,
        "file_hash": kwargs.pop("file_hash", f"ea-{id(kwargs)}"),
        "raw_file_path": kwargs.pop("raw_file_path", "vault/test/file.pdf"),
    }
    payload.update(kwargs)
    inv = Invoice(**payload)
    db.add(inv)
    await db.flush()
    return inv


async def _mark_processed(
    db: AsyncSession,
    inv: Invoice,
    *,
    minutes_after_ingest: int = 4,
) -> None:
    ingested = inv.created_at or datetime.now(timezone.utc)
    processed_at = ingested + timedelta(minutes=minutes_after_ingest)
    await log_event(
        db,
        "invoice_processed",
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
        detail={"status": "processed"},
    )
    row = (
        await db.execute(
            AuditLog.__table__.select().where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "invoice_processed",
            )
        )
    ).first()
    if row is not None:
        log = await db.get(AuditLog, row[0])
        if log is not None:
            log.created_at = processed_at


@pytest.mark.asyncio
async def test_efficiency_automation_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/efficiency-automation")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["kpis"]["documents_processed_ytd"] == 0
    assert body["kpis"]["discount_captured"] is None
    assert body["kpis"]["total_value_delivered"] is None


@pytest.mark.asyncio
async def test_touchless_reconciles_with_process_efficiency(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    start = date(today.year, 7, 1) if today.month >= 7 else date(today.year - 1, 7, 1)
    inv = await _invoice(
        db_session,
        file_hash="ea-stp-1",
        invoice_no="EA-STP-1",
        created_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
    )
    await _mark_processed(db_session, inv, minutes_after_ingest=2)
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    expected = await touchless_pct_from_process_efficiency(
        db_session, TESTING_TENANT_UUID, start, today
    )
    assert dash.kpis.touchless_processing_pct == expected
    assert dash.kpis.straight_through_pct == expected


@pytest.mark.asyncio
async def test_first_pass_is_distinct_from_touchless(db_session: AsyncSession) -> None:
    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    today = date.today()
    start = date(today.year, 7, 1) if today.month >= 7 else date(today.year - 1, 7, 1)
    slice_ = await process_efficiency_slice(db_session, TESTING_TENANT_UUID, start, today)
    assert dash.kpis.first_pass_validation_pct == slice_.first_pass_pct


@pytest.mark.asyncio
async def test_documents_processed_matches_process_efficiency(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    for i in range(2):
        inv = await _invoice(
            db_session,
            file_hash=f"ea-docs-{i}",
            invoice_no=f"EA-DOC-{i}",
            created_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
        await _mark_processed(db_session, inv)
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date(today.year, 7, 1) if today.month >= 7 else date(today.year - 1, 7, 1)
    slice_ = await process_efficiency_slice(db_session, TESTING_TENANT_UUID, start, today)
    assert dash.kpis.documents_processed_ytd == slice_.processed
    assert dash.kpis.documents_processed_ytd >= 2


@pytest.mark.asyncio
async def test_avg_processing_time_from_processed_audit(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    ingested = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    inv = await _invoice(
        db_session,
        file_hash="ea-time-1",
        created_at=ingested,
    )
    await _mark_processed(db_session, inv, minutes_after_ingest=10)
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.avg_processing_minutes == Decimal("10.00")


@pytest.mark.asyncio
async def test_cost_per_invoice_and_hours_saved_formula(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.tenant import Tenant

    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None
    settings = dict(tenant.settings_json or {})
    settings["labor_rate_per_hour"] = 60.0
    tenant.settings_json = settings
    await db_session.flush()

    today = date.today()
    ingested = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    inv = await _invoice(
        db_session,
        file_hash="ea-cost-1",
        created_at=ingested,
    )
    await _mark_processed(db_session, inv, minutes_after_ingest=2)
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.cost_per_invoice == Decimal("2.00")  # 2/60 * 60
    expected_saved = (MANUAL_PROCESSING_MINUTES_BASELINE - Decimal("2")) / Decimal("60")
    assert dash.kpis.hours_saved_ytd == expected_saved.quantize(Decimal("0.01"))
    assert dash.kpis.fte_equivalent == (
        expected_saved / FTE_HOURS_PER_YEAR
    ).quantize(Decimal("0.01"))
    improvement = (
        (MANUAL_COST_PER_INVOICE_BASELINE - dash.kpis.cost_per_invoice)
        / MANUAL_COST_PER_INVOICE_BASELINE
        * Decimal("100")
    ).quantize(Decimal("0.01"))
    assert dash.kpis.cost_improvement_pct == improvement


@pytest.mark.asyncio
async def test_duplicates_prevented_uses_duplicate_skipped_audit(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    shadow = await _invoice(
        db_session,
        file_hash="ea-dup-shadow",
        invoice_no="EA-DUP",
        total=Decimal("500.00"),
        status=InvoiceStatus.DUPLICATE_SKIPPED,
    )
    await log_event(
        db_session,
        "duplicate_skipped",
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=shadow.id,
        detail={"reason": "hash match"},
    )
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.duplicates_prevented_events == 1
    assert dash.kpis.duplicates_prevented_amount == Decimal("500.00")


@pytest.mark.asyncio
async def test_missing_docs_reconciles_with_missing_documents_report(
    db_session: AsyncSession,
) -> None:
    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    expected = await missing_documents_count_from_report(
        db_session, TESTING_TENANT_UUID, start, end
    )
    assert dash.kpis.missing_supporting_docs == expected


@pytest.mark.asyncio
async def test_sync_success_from_accounting_jobs(db_session: AsyncSession) -> None:
    db_session.add(
        AccountingSyncJob(
            tenant_id=TESTING_TENANT_UUID,
            provider="xero",
            job_type="export",
            status=JOB_STATUS_COMPLETED,
        )
    )
    db_session.add(
        AccountingSyncJob(
            tenant_id=TESTING_TENANT_UUID,
            provider="quickbooks",
            job_type="export",
            status=JOB_STATUS_FAILED,
            attempts=5,
        )
    )
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.sync_success_pct == Decimal("50.00")
    assert dash.kpis.sync_dead_letter_count == 1
    assert "XERO" in dash.kpis.sync_providers_label.upper()


@pytest.mark.asyncio
async def test_discount_capture_honest_gap_consistent_with_position_liquidity(
    db_session: AsyncSession,
) -> None:
    pl = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    ea = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert pl.kpis.discount_capture_rate_pct is None
    assert ea.kpis.discount_captured is None
    assert ea.kpis.discount_available is None
    assert ea.kpis.total_value_delivered is None
    assert "discount_capture" in " ".join(ea.meta.coverage_gaps)


@pytest.mark.asyncio
async def test_total_value_delivered_withheld_when_discount_untracked(
    db_session: AsyncSession,
) -> None:
    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.total_value_delivered is None
    assert dash.kpis.automation_savings_amount >= Decimal("0")


@pytest.mark.asyncio
async def test_vault_documents_are_tenant_scoped(
    db_session: AsyncSession,
) -> None:
    await _invoice(db_session, file_hash="ea-vault-a", raw_file_path="vault/a.pdf")
    other = Tenant(
        id=TENANT_B_ID,
        name="EA Vault B",
        slug="ea-vault-b",
        currency="AUD",
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()
    foreign = Invoice(
        tenant_id=TENANT_B_ID,
        vendor="Foreign",
        invoice_no="EA-F",
        invoice_date=date.today(),
        total=Decimal("1.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="ea-vault-b",
        raw_file_path="vault/b.pdf",
    )
    db_session.add(foreign)
    await db_session.commit()

    dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.kpis.vault_documents_total >= 1
    foreign_dash = await build_efficiency_automation_dashboard(
        db_session, tenant_id=TENANT_B_ID
    )
    assert foreign_dash.kpis.vault_documents_total == 1


@pytest.mark.asyncio
async def test_efficiency_automation_does_not_leak_across_tenants(
    anon_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Tenant(
            id=TENANT_A_ID,
            name="EA Iso A",
            slug="ea-iso-a",
            currency="AUD",
            is_active=True,
        )
    )
    db_session.add(
        Tenant(
            id=TENANT_B_ID,
            name="EA Iso B",
            slug="ea-iso-b",
            currency="AUD",
            is_active=True,
        )
    )
    today = datetime.now(timezone.utc)
    for tenant_id, amount, tag in (
        (TENANT_A_ID, Decimal("100.00"), "a"),
        (TENANT_B_ID, Decimal("999.00"), "b"),
    ):
        inv = Invoice(
            tenant_id=tenant_id,
            vendor="Iso",
            invoice_no=f"EA-ISO-{tag}",
            invoice_date=date.today(),
            total=amount,
            currency="AUD",
            status=InvoiceStatus.DUPLICATE_SKIPPED,
            file_hash=f"ea-iso-{tag}",
            raw_file_path=f"vault/{tag}.pdf",
            created_at=today,
        )
        db_session.add(inv)
        await db_session.flush()
        await log_event(
            db_session,
            "duplicate_skipped",
            tenant_id=tenant_id,
            invoice_id=inv.id,
            detail={},
        )
    _user_a, token_a = await seed_admin_user(
        db_session,
        email="ea-iso-a@test.example.com",
        tenant_id=TENANT_A_ID,
        tenant_slug="ea-iso-a",
    )
    _user_b, token_b = await seed_admin_user(
        db_session,
        email="ea-iso-b@test.example.com",
        tenant_id=TENANT_B_ID,
        tenant_slug="ea-iso-b",
    )
    await db_session.commit()

    res_a = await anon_client.get(
        "/api/dashboard/efficiency-automation",
        headers=tenant_auth_headers(token_a, TENANT_A_ID),
    )
    res_b = await anon_client.get(
        "/api/dashboard/efficiency-automation",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_a.json()["data"]["kpis"]["duplicates_prevented_amount"] == "100.00"
    assert res_b.json()["data"]["kpis"]["duplicates_prevented_amount"] == "999.00"
