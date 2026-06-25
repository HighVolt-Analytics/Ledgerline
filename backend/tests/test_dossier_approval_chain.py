"""Approval chain copy should be human-readable, not raw audit tokens."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier_approval_service import (
    _human_detail,
    _human_policy_ref,
    build_dossier_approval_chain,
)
from tests.conftest import TESTING_TENANT_UUID


def test_human_detail_maps_audit_tokens() -> None:
    assert _human_detail("invoice_approved") == "Approved in Approvals"
    assert _human_detail("approval_required cleared") == "Approval gate cleared"
    assert _human_detail("Custom reason") == "Custom reason"


def test_human_policy_ref_hides_internal_slugs() -> None:
    assert _human_policy_ref("DOA-01") == "Buyer authority"
    assert _human_policy_ref("touchless_on_clean_match") is None
    assert _human_policy_ref("invoice_approved") is None
    assert _human_policy_ref("Post") is None


@pytest.mark.asyncio
async def test_approval_chain_uses_plain_language(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        file_hash="approval-chain-human",
    )
    db_session.add(inv)
    await db_session.flush()

    approved_at = datetime(2026, 6, 23, 7, 21, 59, tzinfo=timezone.utc)
    logs = [
        AuditLog(
            event="invoice_approved",
            invoice_id=inv.id,
            created_at=approved_at,
            detail={"actor_name": "Test Approver"},
        ),
    ]

    chain = await build_dossier_approval_chain(
        db_session,
        inv,
        logs,
        definition=None,
        payment=None,
        published=False,
    )

    gate = next(step for step in chain.steps if step.id == "document_gate")
    assert gate.detail == "Approved by Test Approver"
    assert gate.policy_ref == "Playbook policy"

    queue = next(step for step in chain.steps if step.id == "exception_queue")
    assert queue.detail == "Approved in Approvals"
    assert queue.policy_ref is None

    publish = next(step for step in chain.steps if step.id == "publish")
    assert publish.detail == "Waiting to post"
    assert publish.policy_ref is None

    assert "invoice_approved" not in str(chain.model_dump())
