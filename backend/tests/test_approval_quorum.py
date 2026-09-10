"""Amount-tier approval quorum (document steps + escalation)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext
from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.models.user import User, UserRole
from app.services.approval.approval_policy_io import (
    default_policy_dict,
    load_policy_for_tenant,
    save_policy_for_tenant,
    validate_policy_payload,
)
from app.services.approval.approval_quorum_service import (
    ApprovalQuorumForbiddenError,
    actor_in_pool,
    mode_for_module,
    module_for_route_target,
    quorum_met,
    record_approval,
    require_actor_in_pool,
)
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import tenant_auth_headers


def test_amount_tier_policy_defaults() -> None:
    raw = default_policy_dict()
    policy = validate_policy_payload(raw)
    assert "rules" not in policy.model_dump()
    assert "approval_matrix" not in policy.model_dump()
    assert len(policy.amount_approval_tiers) >= 5
    assert mode_for_module(TESTING_TENANT_UUID, "team_expenses") == "amount_tier"
    assert mode_for_module(TESTING_TENANT_UUID, "purchase") == "amount_tier"


def test_module_for_route_target() -> None:
    assert module_for_route_target("Team Expenses") == "team_expenses"
    assert module_for_route_target("Purchase Management") == "purchase"
    assert module_for_route_target("Unknown") == "expenses"


def test_record_approval_idempotent_same_user() -> None:
    chain = record_approval(
        None,
        tenant_id=TESTING_TENANT_UUID,
        module_key="team_expenses",
        user_id=1,
        role="manager",
        name="Mgr One",
        amount=100,
    )
    chain = record_approval(
        chain,
        tenant_id=TESTING_TENANT_UUID,
        module_key="team_expenses",
        user_id=1,
        role="manager",
        name="Mgr One",
        amount=100,
    )
    assert len(chain["approvals"]) == 1
    assert quorum_met(chain)


def test_two_step_tier_needs_second_role() -> None:
    chain = record_approval(
        None,
        tenant_id=TESTING_TENANT_UUID,
        module_key="purchase",
        user_id=1,
        role="manager",
        name="A",
        amount=15_000,
    )
    assert not quorum_met(chain)
    chain = record_approval(
        chain,
        tenant_id=TESTING_TENANT_UUID,
        module_key="purchase",
        user_id=2,
        role="department_head",
        name="B",
        amount=15_000,
    )
    assert quorum_met(chain)


def test_higher_role_can_cover_both_document_steps() -> None:
    chain = record_approval(
        None,
        tenant_id=TESTING_TENANT_UUID,
        module_key="purchase",
        user_id=10,
        role="director",
        name="Director",
        amount=15_000,
    )
    # Director covers step 1 only; still need step 2 from a distinct approval click
    assert not quorum_met(chain)
    chain = record_approval(
        chain,
        tenant_id=TESTING_TENANT_UUID,
        module_key="purchase",
        user_id=11,
        role="director",
        name="Director2",
        amount=15_000,
    )
    assert quorum_met(chain)


def test_admin_cannot_cover_finance_or_manager_step() -> None:
    with pytest.raises(ApprovalQuorumForbiddenError, match="Admin cannot substitute"):
        record_approval(
            None,
            tenant_id=TESTING_TENANT_UUID,
            module_key="expenses",
            user_id=1,
            role="admin",
            name="Admin",
            amount=100,
        )


def test_employee_not_in_pool() -> None:
    ctx = AuthContext(
        user_id=9,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email="bk@test.com",
        role="employee",
    )
    assert actor_in_pool(ctx) is False
    with pytest.raises(ApprovalQuorumForbiddenError):
        require_actor_in_pool(ctx)


def test_manager_in_pool() -> None:
    ctx = AuthContext(
        user_id=9,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email="fm@test.com",
        role="manager",
    )
    assert actor_in_pool(ctx) is True


async def _seed_member(
    db: AsyncSession,
    *,
    email: str,
    role: str,
    full_name: str,
) -> User:
    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email=email,
        password_hash=hash_password("password123"),
        full_name=full_name,
        role=UserRole.ADMIN if role == "admin" else UserRole.MEMBER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await ensure_membership(db, user_id=user.id, tenant_id=TESTING_TENANT_UUID, role=role)
    await db.commit()
    return user


def _token(user: User, role: str) -> str:
    return create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=user.email,
        role=role,
    )


@pytest.mark.asyncio
async def test_approve_api_two_step_amount_tier(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    mgr = await _seed_member(
        db_session,
        email="quorum-mgr@test.com",
        role="manager",
        full_name="Quorum Mgr",
    )
    head = await _seed_member(
        db_session,
        email="quorum-dh@test.com",
        role="department_head",
        full_name="Quorum DH",
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Team Claim",
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("15000.00"),
        route_target="Team Expenses",
        evaluation_status="pending_approval",
        raw_file_path="invoice/test.pdf",
    )
    db_session.add(inv)
    await db_session.commit()

    async def _noop_ensure(*_a, **_k):
        return None

    async def _noop_approve(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.approval.approval_api_service.ensure_stored_file_for_approval",
        _noop_ensure,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_api_service._is_vision_header_review_hold",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_api_service._approve_invoice_for_posting_resume",
        _noop_approve,
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_posting_resumes",
        lambda *_a, **_k: "idle",
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_pipelines",
        lambda *_a, **_k: "idle",
    )

    headers_mgr = tenant_auth_headers(_token(mgr, "manager"), TESTING_TENANT_UUID)
    first = await client.post(f"/api/approvals/{inv.id}/approve", headers=headers_mgr)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["meta"]["quorum_met"] is False
    assert body["meta"]["quorum_recorded"] == 1
    assert body["meta"]["quorum_required"] == 2
    assert body["data"]["status"] == "exception"

    await db_session.refresh(inv)
    assert inv.approval_chain is not None
    assert len(inv.approval_chain["approvals"]) == 1

    again = await client.post(f"/api/approvals/{inv.id}/approve", headers=headers_mgr)
    assert again.status_code == 200
    assert again.json()["meta"]["quorum_recorded"] == 1
    assert again.json()["meta"]["quorum_met"] is False

    headers_dh = tenant_auth_headers(_token(head, "department_head"), TESTING_TENANT_UUID)
    second = await client.post(f"/api/approvals/{inv.id}/approve", headers=headers_dh)
    assert second.status_code == 200, second.text
    assert second.json()["meta"]["quorum_met"] is True

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_escalate_api_raises_current_step(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    mgr = await _seed_member(
        db_session,
        email="esc-mgr@test.com",
        role="manager",
        full_name="Esc Mgr",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Escalate Me",
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("15000.00"),
        route_target="Team Expenses",
        raw_file_path="invoice/test.pdf",
    )
    db_session.add(inv)
    await db_session.commit()

    headers = tenant_auth_headers(_token(mgr, "manager"), TESTING_TENANT_UUID)
    res = await client.post(
        f"/api/approvals/{inv.id}/escalate",
        headers=headers,
        json={"note": "Manager unavailable"},
    )
    assert res.status_code == 200, res.text
    await db_session.refresh(inv)
    assert inv.approval_chain is not None
    step0 = inv.approval_chain["steps"][0]
    assert step0["escalated_to_role"] == "Department Head"
    assert inv.approval_chain["escalations"]

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_reject_clears_approval_chain(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    mgr = await _seed_member(
        db_session,
        email="reject-chain@test.com",
        role="manager",
        full_name="Reject Chain",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Clear Me",
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("50.00"),
        route_target="Team Expenses",
        approval_chain={
            "module": "team_expenses",
            "mode": "amount_tier",
            "required": 1,
            "approvals": [
                {
                    "user_id": mgr.id,
                    "role": "manager",
                    "name": "Reject Chain",
                    "at": "2026-01-01T00:00:00+00:00",
                }
            ],
        },
    )
    db_session.add(inv)
    await db_session.commit()

    headers = tenant_auth_headers(_token(mgr, "manager"), TESTING_TENANT_UUID)
    res = await client.post(f"/api/approvals/{inv.id}/reject", headers=headers)
    assert res.status_code == 200, res.text
    await db_session.refresh(inv)
    assert inv.approval_chain is None

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_employee_forbidden_from_quorum_pool(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    policy = load_policy_for_tenant(TESTING_TENANT_UUID)
    policy.matrix["Employee"]["Approve"] = True
    save_policy_for_tenant(TESTING_TENANT_UUID, policy)

    bk = await _seed_member(
        db_session,
        email="bk-quorum@test.com",
        role="employee",
        full_name="Bookkeeper Q",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Pool Block",
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("10.00"),
        route_target="Expenses Management",
    )
    db_session.add(inv)
    await db_session.commit()

    headers = tenant_auth_headers(_token(bk, "employee"), TESTING_TENANT_UUID)
    res = await client.post(f"/api/approvals/{inv.id}/approve", headers=headers)
    assert res.status_code == 403

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_purchase_variance_two_step_from_invoice_amount(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()

    mgr = await _seed_member(
        db_session,
        email="var-mgr@test.com",
        role="manager",
        full_name="Var Mgr",
    )
    head = await _seed_member(
        db_session,
        email="var-dh@test.com",
        role="department_head",
        full_name="Var DH",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        total=Decimal("15000.00"),
        route_target="Purchase Management",
        raw_file_path="invoice/test.pdf",
    )
    db_session.add(inv)
    await db_session.flush()
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-QUORUM-1",
        vendor="Acme",
        status=PurchaseOrderStatus.VARIANCE_PENDING,
        variance_approved=False,
        invoice_id=inv.id,
    )
    db_session.add(po)
    await db_session.commit()

    h1 = tenant_auth_headers(_token(mgr, "manager"), TESTING_TENANT_UUID)
    r1 = await client.post(f"/api/purchases/{po.id}/approve-variance", headers=h1)
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["variance_approved"] is False

    await db_session.refresh(po)
    assert po.variance_approval_chain is not None
    assert po.variance_approved is False

    h2 = tenant_auth_headers(_token(head, "department_head"), TESTING_TENANT_UUID)
    r2 = await client.post(f"/api/purchases/{po.id}/approve-variance", headers=h2)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["variance_approved"] is True

    get_settings.cache_clear()
