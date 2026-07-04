"""Regression: /classification-review must not be shadowed by /{invoice_id}."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import EVAL_AWAITING_CLASSIFICATION
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_classification_review_route_not_int_path(client: AsyncClient) -> None:
    res = await client.get("/api/invoices/classification-review")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["error"] is None
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_classification_review_returns_queued_invoice(
    client: AsyncClient,
    db_session,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status=EVAL_AWAITING_CLASSIFICATION,
        llm_suggested_dt="DT-03",
        llm_confidence=0.51,
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/invoices/classification-review")
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert any(row["invoice_id"] == inv.id for row in rows)
    match = next(row for row in rows if row["invoice_id"] == inv.id)
    assert match["llm_suggested_dt"] == "DT-03"
    assert match["llm_confidence"] == pytest.approx(0.51, rel=1e-3)
