"""Tenant isolation for classification learning events."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classification_learning import ClassificationLearningEvent
from app.models.tenant import Tenant
from app.services.classification_learning_service import (
    few_shot_examples_for_tenant,
    purge_learning_events_for_document_type,
    record_learning_event,
    record_learning_from_resolution,
)
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_rls import apply_rls_session_context, clear_rls_session_context


@pytest.mark.asyncio
async def test_few_shot_examples_scoped_to_tenant(db_session: AsyncSession) -> None:
    other_tid = uuid.uuid4()
    db_session.add(Tenant(id=other_tid, name="Other", slug="other-learn"))
    await db_session.flush()

    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        file_hash="aaa",
        human_confirmed_dt="DT-03",
        llm=None,
    )
    await record_learning_event(
        db_session,
        tenant_id=other_tid,
        invoice_id=2,
        file_hash="bbb",
        human_confirmed_dt="DT-16",
        llm=None,
    )
    await db_session.flush()

    examples = await few_shot_examples_for_tenant(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert len(examples) == 1
    assert examples[0]["human_confirmed_dt"] == "DT-03"


@pytest.mark.asyncio
async def test_few_shot_examples_include_rich_context(db_session: AsyncSession) -> None:
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=10,
        file_hash="cargo-hash",
        human_confirmed_dt="DT-26",
        llm_suggested_dt="DT-02",
        policy_winner_dt="DT-01",
        review_reasons=["DT_MISMATCH", "PERSPECTIVE_AMBIGUOUS"],
        document_heading="CARGO CLEARANCE PERMIT",
        text_excerpt="CARGO CLEARANCE PERMIT\nPERMIT NO: ABC123",
    )
    await db_session.flush()

    examples = await few_shot_examples_for_tenant(
        db_session, tenant_id=TESTING_TENANT_UUID, limit=3
    )
    assert len(examples) == 1
    row = examples[0]
    assert row["human_confirmed_dt"] == "DT-26"
    assert row["llm_suggested_dt"] == "DT-02"
    assert row["policy_winner_dt"] == "DT-01"
    assert "CARGO CLEARANCE PERMIT" in row["text_excerpt"]
    assert "DT_MISMATCH" in row["review_reasons"]
    assert "DT-02" in row["note"] and "DT-26" in row["note"]


@pytest.mark.asyncio
async def test_record_learning_from_resolution_merges_invoice_text(
    db_session: AsyncSession,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus

    inv = Invoice(
        id=42,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        document_text="DELIVERY ORDER\nRef 999",
        file_hash="del-hash",
        llm_suggested_dt="DT-02",
    )
    db_session.add(inv)
    await db_session.flush()

    event = await record_learning_from_resolution(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice=inv,
        human_confirmed_dt="DT-11",
        classification_detail={
            "llm_suggested_dt": "DT-02",
            "policy_winner_dt": "DT-01",
            "review_reasons": ["DT_MISMATCH"],
        },
    )
    assert event.human_confirmed_dt == "DT-11"
    assert event.llm_suggested_dt == "DT-02"
    assert event.policy_winner_dt == "DT-01"
    assert event.review_reasons == ["DT_MISMATCH"]
    assert isinstance(event.llm_response, dict)
    assert event.llm_response.get("document_heading") == "DELIVERY ORDER"
    assert "DELIVERY ORDER" in str(event.llm_response.get("text_excerpt"))


@pytest.mark.asyncio
async def test_purge_learning_events_for_deleted_document_type(
    db_session: AsyncSession,
) -> None:
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        file_hash="a",
        human_confirmed_dt="DT-26",
    )
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=2,
        file_hash="b",
        human_confirmed_dt="DT-03",
    )
    await db_session.flush()

    removed = await purge_learning_events_for_document_type(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        document_type_code="dt-26",
    )
    assert removed == 1

    rows = (
        await db_session.execute(
            select(ClassificationLearningEvent).where(
                ClassificationLearningEvent.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalars().all()
    assert {row.human_confirmed_dt for row in rows} == {"DT-03"}


@pytest.mark.asyncio
async def test_few_shot_examples_skip_removed_catalogue_codes(
    db_session: AsyncSession,
) -> None:
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=3,
        file_hash="c",
        human_confirmed_dt="DT-26",
    )
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=4,
        file_hash="d",
        human_confirmed_dt="DT-03",
    )
    await db_session.flush()

    examples = await few_shot_examples_for_tenant(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        valid_dt_codes={"DT-03"},
    )
    assert len(examples) == 1
    assert examples[0]["human_confirmed_dt"] == "DT-03"


@pytest.mark.asyncio
async def test_rls_hides_other_tenant_learning_events(db_session: AsyncSession) -> None:
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL RLS is not active on SQLite test database")

    other_tid = uuid.uuid4()
    db_session.add(Tenant(id=other_tid, name="Other", slug="other-learn-rls"))
    db_session.add(
        ClassificationLearningEvent(
            tenant_id=other_tid,
            invoice_id=99,
            human_confirmed_dt="DT-16",
        )
    )
    await db_session.flush()

    await apply_rls_session_context(db_session, TESTING_TENANT_UUID)
    rows = (
        await db_session.execute(
            select(ClassificationLearningEvent).where(
                ClassificationLearningEvent.tenant_id == other_tid
            )
        )
    ).scalars().all()
    assert rows == []

    await clear_rls_session_context(db_session)
    ctx = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    assert ctx.scalar() in ("", None)
