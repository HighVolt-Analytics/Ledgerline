
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.shared.currency import convert_to_base


@pytest.mark.asyncio
async def test_dashboard_badges_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/badges")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["inbox_count"] == 0
    assert data["pending_approval"] == 0
    assert data["team_expenses_count"] == 0
    assert data["payments_queue_count"] == 0
    assert "integrations_connected" in data


@pytest.mark.asyncio
async def test_dashboard_stats_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total_invoices"] == 0
    assert data["synced_percent"] == 0
    assert data["pending_approval"] == 0
    assert data["inbox_count"] == 0
    assert data["distinct_vendors"] == 0
    assert data["docs_via_email"] == 0
    assert data["docs_via_upload"] == 0


@pytest.mark.asyncio
async def test_dashboard_overview(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Corp",
        total=Decimal("1000.00"),
        due_date=date.today() + timedelta(days=5),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            event="invoice_processed",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/overview?activity_limit=5")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["stats"]["total_invoices"] == 1
    assert body["stats"]["processed"] == 1
    assert body["stats"]["distinct_vendors"] == 1
    assert body["stats"]["docs_via_upload"] == 1
    assert body["stats"]["total_value_aud"] == "1000.00"
    assert len(body["activity"]) >= 1
    assert body["top_vendors"][0]["vendor"] == "Acme Corp"
    assert len(body["cash_forecast"]) == 6
    seven_day = next(b for b in body["cash_forecast"] if b["label"] == "7 days")
    assert Decimal(seven_day["amount"]) == convert_to_base(Decimal("1000.00"), "AUD")
    assert len(body["invoice_volume_sparkline"]) >= 1
    assert "period" in body
    assert "mailbox_breakdown" in body
    assert "anomalies" in body
    assert "kpi_trends" in body
    assert "kpi_sparklines" in body
    assert len(body["kpi_sparklines"]["docs_via_email"]) == 7
    assert body["period_has_data"] is True
    assert body["stats"]["base_currency"] == "AUD"
    assert "total_value" in body["stats"]


@pytest.mark.asyncio
async def test_dashboard_activity_includes_duplicate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    original = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Dup Vendor",
        invoice_no="INV-DUP-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash-dup-original",
    )
    shadow = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Dup Vendor",
        invoice_no="INV-DUP-1",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add_all([original, shadow])
    await db_session.flush()
    db_session.add(
        AuditLog(
            event="duplicate_skipped",
            invoice_id=shadow.id,
            detail={
                "original_invoice_id": original.id,
                "filename": "invoice.pdf",
                "source": "email",
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/overview?activity_limit=10")
    assert res.status_code == 200
    activity = res.json()["data"]["activity"]
    dup_rows = [row for row in activity if row["event"] == "duplicate_skipped"]
    assert len(dup_rows) >= 1
    assert dup_rows[0]["summary"] is not None
    assert "Duplicate file skipped" in dup_rows[0]["summary"]


@pytest.mark.asyncio
async def test_pending_approval_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(tenant_id=TESTING_TENANT_UUID,
            vendor="X",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="ex1",
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/stats")
    assert res.json()["data"]["pending_approval"] == 1
    assert res.json()["data"]["exceptions"] == 1


@pytest.mark.asyncio
async def test_total_value_counts_processed_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Booked KPIs exclude exception, rejected, and duplicate invoices."""
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Booked Co",
                total=Decimal("1000.00"),
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="dash-booked",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Exception Co",
                total=Decimal("500.00"),
                status=InvoiceStatus.EXCEPTION,
                currency="AUD",
                file_hash="dash-exc",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Rejected Co",
                total=Decimal("250.00"),
                status=InvoiceStatus.REJECTED,
                currency="AUD",
                file_hash="dash-rej",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Dupe Co",
                total=Decimal("100.00"),
                status=InvoiceStatus.DUPLICATE_SKIPPED,
                currency="AUD",
                file_hash="dash-dupe",
            ),
        ]
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/stats")
    data = res.json()["data"]
    assert Decimal(data["total_value_aud"]) == Decimal("1000.00")
    assert data["processed"] == 1
    assert data["rejected"] == 1
    assert data["distinct_vendors"] == 1

    overview = await client.get("/api/dashboard/overview")
    body = overview.json()["data"]
    assert len(body["top_vendors"]) == 1
    assert body["top_vendors"][0]["vendor"] == "Booked Co"
    assert Decimal(body["top_vendors"][0]["amount"]) == convert_to_base(
        Decimal("1000.00"), "AUD"
    )
    forecast_total = sum(
        Decimal(b["amount"]) for b in body["cash_forecast"]
    )
    assert forecast_total == Decimal("0")


@pytest.mark.asyncio
async def test_reject_processed_updates_dashboard_value(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Spend Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-010_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spend Co",
        invoice_no="INV-010",
        invoice_date=date(2026, 5, 4),
        due_date=date.today() + timedelta(days=5),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash-reject-flow",
        raw_file_path=str(pdf),
        total=Decimal("1500.00"),
    )
    db_session.add(inv)
    await db_session.flush()

    before = (await client.get("/api/dashboard/stats")).json()["data"]
    assert Decimal(before["total_value_aud"]) == Decimal("1500.00")
    assert before["processed"] == 1
    assert before["rejected"] == 0
    assert before["synced_percent"] == 100

    reject_res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert reject_res.status_code == 200

    after = (await client.get("/api/dashboard/stats")).json()["data"]
    assert Decimal(after["total_value_aud"]) == Decimal("0")
    assert after["processed"] == 0
    assert after["rejected"] == 1
    assert after["synced_percent"] == 0

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    assert overview["top_vendors"] == []
    seven_day = next(b for b in overview["cash_forecast"] if b["label"] == "7 days")
    assert Decimal(seven_day["amount"]) == Decimal("0")


@pytest.mark.asyncio
async def test_nav_badges_team_expenses_and_payments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Team Vendor",
                status=InvoiceStatus.VALIDATING,
                route_target="Team Expenses",
                currency="AUD",
                file_hash="badge-team",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Payable Co",
                status=InvoiceStatus.PROCESSED,
                due_date=date.today() + timedelta(days=3),
                total=Decimal("500.00"),
                currency="AUD",
                file_hash="badge-pay",
            ),
        ]
    )
    await db_session.flush()

    data = (await client.get("/api/dashboard/badges")).json()["data"]
    assert data["team_expenses_count"] == 1
    assert data["payments_queue_count"] == 1


@pytest.mark.asyncio
async def test_docs_via_upload_counts_non_email_sources(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Email Co",
                status=InvoiceStatus.PENDING,
                email_sender="vendor@example.com",
                currency="AUD",
                file_hash="dash-email",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Upload Co",
                status=InvoiceStatus.PENDING,
                currency="AUD",
                file_hash="dash-upload",
            ),
        ]
    )
    await db_session.flush()

    stats = (await client.get("/api/dashboard/stats")).json()["data"]
    assert stats["docs_via_email"] == 1
    assert stats["docs_via_upload"] == 1


@pytest.mark.asyncio
async def test_dashboard_anomaly_label_uses_document_ref_not_db_invoice_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression: do not synthesize INV-{db_id} — it collides with real invoice numbers."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_ref="DOC-88",
        invoice_no="INV-173",
        vendor="ONEGLOBE CONSOLIDATORS (S) PTE. LTD.",
        status=InvoiceStatus.VALIDATING,
        route_target="Purchase Management",
        evaluation_status="needs_review",
        currency="AUD",
        file_hash="dash-anomaly-doc-ref",
    )
    db_session.add(inv)
    await db_session.flush()

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    row = next(
        r for r in overview["anomalies"] if r.get("invoice_id") == inv.id
    )
    assert row["document_ref"] == "DOC-88"
    assert row["description"].startswith("DOC-88 · INV-173")
    assert not row["description"].startswith("INV-173 ·")


@pytest.mark.asyncio
async def test_dashboard_anomalies_sales_invoice_no_missing_po(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Harbour View Hotel",
            invoice_no="INV-9001",
            status=InvoiceStatus.EXCEPTION,
            route_target="Sales Management",
            so_reference="SO-DEMO-100",
            currency="AUD",
            file_hash="dash-sales-no-po-anomaly",
        )
    )
    await db_session.flush()

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    missing_po = [
        row for row in overview["anomalies"] if row["tag"] == "Missing PO" and row["invoice_id"]
    ]
    assert not any("INV-9001" in row["description"] for row in missing_po)


@pytest.mark.asyncio
async def test_dashboard_top_vendors_marks_sales_as_customer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Harbour View Hotel",
            status=InvoiceStatus.PROCESSED,
            route_target="Sales Management",
            total=Decimal("450.00"),
            currency="AUD",
            file_hash="dash-top-customer",
        )
    )
    await db_session.flush()

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    assert overview["top_vendors"]
    assert overview["top_vendors"][0]["counterparty_label"] == "Customer"


@pytest.mark.asyncio
async def test_dashboard_anomalies_include_rule_book_routing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Unknown Supplier Pty Ltd",
                status=InvoiceStatus.MAPPING,
                route_target="Purchase Management",
                evaluation_status="pending_vendor",
                currency="AUD",
                file_hash="dash-pending-vendor",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Ambiguous Co",
                status=InvoiceStatus.VALIDATING,
                route_target="Team Expenses",
                evaluation_status="needs_review",
                currency="AUD",
                file_hash="dash-needs-review",
            ),
        ]
    )
    await db_session.flush()

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    tags = {row["tag"] for row in overview["anomalies"]}
    assert "Pending vendor" in tags
    assert "Needs review" in tags


@pytest.mark.asyncio
async def test_dashboard_overview_panels_capture_and_executive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Email Vendor",
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                total=Decimal("100.00"),
                capture_source="email",
                email_sender="ap@vendor.com",
                evaluation_status="auto_coded",
                file_hash="dash-panel-email",
                uploaded_by_email="ops@example.com",
                uploaded_by_name="Ops User",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="WA Vendor",
                status=InvoiceStatus.EXCEPTION,
                currency="AUD",
                total=Decimal("50.00"),
                capture_source="whatsapp",
                whatsapp_connection_id=1,
                evaluation_status="pending_approval",
                file_hash="dash-panel-wa",
                uploaded_by_email="ops@example.com",
                uploaded_by_name="Ops User",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Upload Vendor",
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                total=Decimal("25.00"),
                capture_source="upload",
                evaluation_status="needs_review",
                file_hash="dash-panel-upload",
            ),
        ]
    )
    await db_session.flush()

    body = (await client.get("/api/dashboard/overview")).json()["data"]

    by_id = {row["id"]: row for row in body["capture_sources"]}
    assert by_id["email"]["document_count"] == 1
    assert by_id["whatsapp"]["document_count"] == 0  # EXCEPTION — not PROCESSED
    assert by_id["upload"]["document_count"] == 1
    assert by_id["viber"]["document_count"] == 0
    # email STP: full 12 min; upload assisted: half of 11 → 6
    assert by_id["email"]["time_saved_minutes"] == 12
    assert by_id["upload"]["time_saved_minutes"] == 6
    assert by_id["email"]["cost_saved"] > 0

    exec_kpis = body["executive_kpis"]
    assert exec_kpis["documents_processed"] == 2
    assert exec_kpis["time_saved_minutes"] == 18
    assert exec_kpis["avg_time_saved_per_doc_minutes"] == 9
    assert exec_kpis["automation_efficiency_pct"] == 50  # 1 STP of 2 PROCESSED
    assert exec_kpis["cost_saved"] == 14  # 18/60 * 45

    assert body["approval_queue"]["pending"] >= 1
    assert body["approval_queue"]["value_label"] != "—"

    assert len(body["extraction_quality"]) == 4
    assert {p["metric"] for p in body["extraction_quality"]} == {
        "Header",
        "Line items",
        "Tax/GST",
        "GL coding",
    }

    assert body["attention"]["priority"]["cta_href"]
    assert body["attention"]["processed"]["value"] is not None
    assert len(body["attention"]["processed"]["bars"]) == 7
    assert len(body["attention"]["turnaround"]["bars"]) == 7
    # Bars are live processed counts (not create-volume); all ints ≥ 0.
    assert all(isinstance(v, int) and v >= 0 for v in body["attention"]["processed"]["bars"])
    assert all(isinstance(v, int) and v >= 0 for v in body["attention"]["turnaround"]["bars"])
    assert body["attention"]["processed"]["label"] == "Processed today"
    assert body["attention"]["turnaround"]["label"] == "Average turnaround"

    ops = body["operations"]["windows"]
    assert "7d" in ops and "30d" in ops and "month" in ops
    all_snap = next(m for m in ops["month"] if m["id"] == "all")
    assert all_snap["documents_processed"] >= 1
    member = next(
        (m for m in ops["month"] if m["id"] == "ops@example.com"),
        None,
    )
    assert member is not None
    assert member["label"] == "Ops User"

    user_ids = {m["id"] for m in body["user_layer"]}
    assert user_ids == {
        "email_mapped",
        "phone_synced",
        "doc_types",
        "manual_handoff",
        "vendors",
    }
    for metric in body["user_layer"]:
        stages = metric["stages"]
        for key in (
            "document_fetched",
            "pending_confirmation",
            "pending_approval",
            "pending_posting",
            "pending_payment",
        ):
            assert key in stages
            assert isinstance(stages[key], int)


@pytest.mark.asyncio
async def test_dashboard_overview_risk_buckets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Dup Co",
                status=InvoiceStatus.DUPLICATE_SKIPPED,
                currency="AUD",
                file_hash="dash-risk-dup",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Fraud Co",
                status=InvoiceStatus.EXCEPTION,
                currency="AUD",
                document_type_code="DT-21",
                file_hash="dash-risk-fraud",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Bank Co",
                status=InvoiceStatus.EXCEPTION,
                currency="AUD",
                document_type_code="DT-23",
                file_hash="dash-risk-bank",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Brand New Vendor XYZ",
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                total=Decimal("10.00"),
                file_hash="dash-risk-new-cp",
            ),
        ]
    )
    await db_session.flush()

    body = (await client.get("/api/dashboard/overview")).json()["data"]
    by_id = {row["id"]: row for row in body["risk_compliance"]}
    assert by_id["duplicates"]["count"] >= 1
    assert by_id["fraud"]["count"] >= 1
    assert by_id["bank"]["count"] >= 1
    assert by_id["counterparties"]["count"] >= 1
    assert by_id["fraud"]["href"].endswith("DT-21")
    assert by_id["bank"]["href"].endswith("DT-23")


@pytest.mark.asyncio
async def test_attention_processed_today_uses_audit_not_volume(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Processed today / bars come from invoice_processed events (tenant-local day)."""
    from app.tenant_settings import tenant_today
    from app.models.tenant import Tenant

    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None
    today = tenant_today(tenant)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Attention Processed Vendor",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("10.00"),
        capture_source="upload",
        evaluation_status="auto_coded",
        file_hash="dash-attn-processed-today",
    )
    db_session.add(inv)
    await db_session.flush()

    # Created earlier this week but processed today → counts for today.
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            event="invoice_processed",
            detail={"source": "test"},
        )
    )
    await db_session.flush()

    body = (await client.get("/api/dashboard/overview")).json()["data"]
    attn = body["attention"]
    assert int(attn["processed"]["value"]) >= 1
    assert attn["processed"]["bars"][-1] >= 1
    assert len(attn["processed"]["bars"]) == 7
    # Turnaround value is from last-7-day window (not a hardcoded placeholder).
    assert attn["turnaround"]["value"] not in {"", None}
    assert "this week" in attn["turnaround"]["delta_text"] or "prior week" in attn[
        "turnaround"
    ]["delta_text"] or "no processed" in attn["turnaround"]["delta_text"]
    _ = today  # used for clarity / future assertions


@pytest.mark.asyncio
async def test_extraction_quality_prefers_di_field_confidence(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Extraction Quality points should follow OCR field_confidence when present."""
    import uuid

    from app.models.classification_learning import InvoiceOcrArtifact

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Quality Vendor",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("100.00"),
        subtotal=Decimal("90.00"),
        gst=Decimal("10.00"),
        invoice_no="EQ-1",
        capture_source="upload",
        evaluation_status="auto_coded",
        account_code="600",
        account_name="Expenses",
        file_hash="dash-eq-di-conf",
    )
    db_session.add(inv)
    await db_session.flush()

    db_session.add(
        InvoiceOcrArtifact(
            id=uuid.uuid4(),
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            file_hash="dash-eq-di-conf",
            di_model="prebuilt-invoice",
            payload_json={
                "field_confidence": {
                    "vendor": 0.91,
                    "invoice_no": 0.88,
                    "invoice_date": 0.80,
                    "due_date": 0.70,
                    "currency": 0.95,
                    "po_reference": 0.60,
                    "gst": 0.40,
                    "subtotal": 0.42,
                    "total": 0.44,
                    "line_items": 0.25,
                },
                "di_line_item_confidences": [0.20, 0.22],
            },
        )
    )
    await db_session.flush()

    body = (await client.get("/api/dashboard/overview")).json()["data"]
    by_metric = {row["metric"]: row["accuracy"] for row in body["extraction_quality"]}
    # Header ≈ mean of 91,88,80,70,95,60
    assert 70 <= by_metric["Header"] <= 90
    # Line items from di_line_item_confidences mean ≈ 21
    assert 15 <= by_metric["Line items"] <= 30
    # Tax ≈ mean of 40,42,44
    assert 35 <= by_metric["Tax/GST"] <= 50
    # GL coded with code+name+auto → high mapping quality
    assert by_metric["GL coding"] >= 90


def test_normalize_and_score_invoice_metrics_unit() -> None:
    from app.services.reports.dashboard_extraction_quality import (
        normalize_confidence_pct,
        score_invoice_metrics,
    )

    assert normalize_confidence_pct(0.85) == 85.0
    assert normalize_confidence_pct(85) == 85.0
    assert normalize_confidence_pct(None) is None

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unit Vendor",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("10.00"),
        evaluation_status="needs_review",
        file_hash="eq-unit",
    )
    scores = score_invoice_metrics(
        inv,
        ocr_payload={
            "field_confidence": {"vendor": 0.5, "invoice_no": 0.5},
            "di_line_item_confidences": [0.1],
        },
    )
    assert scores["Line items"] == 10.0
    assert "Header" in scores
    assert "Tax/GST" in scores
    assert "GL coding" in scores


def test_extraction_quality_uses_invoice_llm_confidence() -> None:
    """DI/classification path stores llm_confidence on invoice — should count."""
    from app.services.reports.dashboard_extraction_quality import (
        aggregate_extraction_quality,
        score_invoice_metrics,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="LLM Vendor",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("100.00"),
        subtotal=Decimal("90.00"),
        gst=Decimal("10.00"),
        invoice_no="LLM-1",
        evaluation_status="auto_coded",
        llm_confidence=0.95,
        document_type_confidence=0.95,
        account_code="6100",
        account_name="Marketing",
        file_hash="eq-llm-conf",
    )
    inv.id = 900003
    scores = score_invoice_metrics(inv, ocr_payload=None)
    assert scores["Header"] == 95.0
    assert scores["Tax/GST"] == 95.0
    assert scores["Line items"] == 80.8  # 95 * 0.85

    agg = dict(aggregate_extraction_quality([inv], {}))
    assert agg["Header"] == 95.0


def test_extraction_quality_includes_vision_header_confidence() -> None:
    """Understood-path vision_header_confidence drives Header/Tax when DI is absent."""
    from app.services.reports.dashboard_extraction_quality import (
        aggregate_extraction_quality,
        score_invoice_metrics,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vision Vendor",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("50.00"),
        subtotal=Decimal("45.00"),
        gst=Decimal("5.00"),
        invoice_no="V-1",
        evaluation_status="vision_header_review",
        extracted_fields={
            "vision_header_confidence": "0.82",
            "canonical_document_type": "commercial_invoice",
            "field_confidence": {"line_items": 0.55},
        },
        file_hash="eq-vision-unit",
    )
    # ORM may not assign id until flush; aggregate uses inv.id
    inv.id = 900001
    scores = score_invoice_metrics(inv, ocr_payload=None)
    assert scores["Header"] == 82.0
    assert scores["Tax/GST"] == 82.0
    assert scores["Line items"] == 55.0

    # Heuristic-only invoice is excluded from aggregate.
    bare = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Bare",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        account_code="9999",
        account_name="Suspense Account",
        file_hash="eq-bare",
    )
    bare.id = 900002
    agg = aggregate_extraction_quality([inv, bare], {})
    by_m = dict(agg)
    assert by_m["Header"] == 82.0
    assert by_m["Line items"] == 55.0
    # Vision doc has no GL code → optional empty heuristic (~52), not inflated coding.
    assert by_m["GL coding"] <= 60


def test_dashboard_savings_math() -> None:
    from app.services.reports.dashboard_savings import (
        ASSISTED_CREDIT,
        STP_CREDIT,
        cost_saved_from_minutes,
        credit_factor,
        minutes_saved_per_doc,
        time_saved_minutes,
    )

    assert credit_factor(is_processed=False, is_stp=False) == 0.0
    assert credit_factor(is_processed=True, is_stp=True) == STP_CREDIT
    assert credit_factor(is_processed=True, is_stp=False) == ASSISTED_CREDIT

    assert minutes_saved_per_doc("email", credit_factor=STP_CREDIT) == 12
    assert minutes_saved_per_doc("whatsapp", credit_factor=ASSISTED_CREDIT) == 8
    assert minutes_saved_per_doc("upload", credit_factor=0) == 0
    assert time_saved_minutes(2, "upload", credit_factor=STP_CREDIT) == 22
    assert cost_saved_from_minutes(60) == 45
    assert cost_saved_from_minutes(60, labor_rate_per_hour=90) == 90
    assert cost_saved_from_minutes(18, labor_rate_per_hour=45) == 14


@pytest.mark.asyncio
async def test_dashboard_cost_saved_uses_tenant_labor_rate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.tenant import Tenant

    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None
    settings = dict(tenant.settings_json or {})
    settings["labor_rate_per_hour"] = 60
    tenant.settings_json = settings
    await db_session.flush()

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Labor Rate Vendor",
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            total=Decimal("10.00"),
            capture_source="email",
            evaluation_status="auto_coded",
            file_hash="dash-labor-rate-email",
        )
    )
    await db_session.flush()

    body = (await client.get("/api/dashboard/overview")).json()["data"]
    # 12 min STP email @ 60/hr → 12/60 * 60 = 12
    assert body["executive_kpis"]["time_saved_minutes"] >= 12
    assert body["executive_kpis"]["cost_saved"] >= 12


@pytest.mark.asyncio
async def test_institution_labor_rate_roundtrip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    before = (await client.get("/api/tenants/current/institution")).json()["data"]
    assert before["labor_rate_per_hour"] == 45.0 or before["labor_rate_per_hour"] > 0

    updated = (
        await client.patch(
            "/api/tenants/current/institution",
            json={"labor_rate_per_hour": 72.5},
        )
    ).json()["data"]
    assert updated["labor_rate_per_hour"] == 72.5

    again = (await client.get("/api/tenants/current/institution")).json()["data"]
    assert again["labor_rate_per_hour"] == 72.5
