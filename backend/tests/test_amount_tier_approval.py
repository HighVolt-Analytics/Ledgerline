"""Amount-tier approval matrix: resolution, escalation, payment gate."""

from __future__ import annotations

import uuid

import pytest

from app.services.approval.amount_tier_approval import (
    DEFAULT_AMOUNT_APPROVAL_TIERS,
    AmountTierApprovalError,
    apply_document_approval,
    build_chain_from_amount,
    document_quorum_met,
    escalate_current_document_step,
    find_tier_for_amount,
    payment_step_role,
    require_payment_approver_role,
    resolve_steps_for_amount,
)
from app.services.approval.approval_quorum_service import (
    ApprovalQuorumForbiddenError,
    quorum_met,
    record_approval,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_find_tier_bands() -> None:
    assert find_tier_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 0)["id"] == "tier-0-5k"
    assert find_tier_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 5000)["id"] == "tier-0-5k"
    assert find_tier_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 5001)["id"] == "tier-5k-20k"
    assert find_tier_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 250000)["id"] == "tier-50k-250k"
    assert find_tier_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 250001)["id"] == "tier-250k-plus"


def test_resolve_steps_separates_payment() -> None:
    _, steps = resolve_steps_for_amount(DEFAULT_AMOUNT_APPROVAL_TIERS, 100_000)
    kinds = [(s.key, s.kind, s.role) for s in steps]
    assert kinds == [
        ("approval_1", "document", "Department Head"),
        ("approval_2", "document", "Finance Manager"),
        ("approval_3", "payment", "CFO"),
    ]
    assert payment_step_role(DEFAULT_AMOUNT_APPROVAL_TIERS, 100_000) == "CFO"
    assert payment_step_role(DEFAULT_AMOUNT_APPROVAL_TIERS, 100) is None


def test_low_amount_one_document_step() -> None:
    chain = build_chain_from_amount(
        tenant_id=uuid.uuid4(),
        module_key="expenses",
        amount=100,
        tiers=DEFAULT_AMOUNT_APPROVAL_TIERS,
    )
    assert chain["required"] == 1
    assert [s["key"] for s in chain["steps"] if s["kind"] == "document"] == ["approval_1"]
    chain = apply_document_approval(chain, user_id=1, role="manager", name="Mgr")
    assert document_quorum_met(chain)
    assert chain["steps"][0]["role"] == "Manager"


def test_mid_tier_needs_two_roles_or_higher_cover() -> None:
    chain = build_chain_from_amount(
        tenant_id=uuid.uuid4(),
        module_key="purchase",
        amount=15_000,
        tiers=DEFAULT_AMOUNT_APPROVAL_TIERS,
    )
    assert chain["required"] == 2
    with pytest.raises(AmountTierApprovalError):
        apply_document_approval(chain, user_id=9, role="employee", name="Emp")
    chain = apply_document_approval(chain, user_id=1, role="manager", name="Mgr")
    assert not document_quorum_met(chain)
    # Finance Manager outranks Department Head and can cover step 2
    chain = apply_document_approval(
        chain, user_id=2, role="finance_manager", name="FM"
    )
    assert document_quorum_met(chain)


def test_escalate_raises_pending_step() -> None:
    chain = build_chain_from_amount(
        tenant_id=uuid.uuid4(),
        module_key="expenses",
        amount=15_000,
        tiers=DEFAULT_AMOUNT_APPROVAL_TIERS,
    )
    chain = escalate_current_document_step(chain, note="on leave", actor_role="manager")
    assert chain["steps"][0]["escalated_to_role"] == "Department Head"
    # Department Head can now cover the escalated first step
    chain = apply_document_approval(
        chain, user_id=3, role="department_head", name="DH"
    )
    assert chain["steps"][0]["status"] == "approved"
    assert not document_quorum_met(chain)


def test_payment_approver_gate() -> None:
    require_payment_approver_role(DEFAULT_AMOUNT_APPROVAL_TIERS, 100_000, "cfo")
    with pytest.raises(AmountTierApprovalError):
        require_payment_approver_role(
            DEFAULT_AMOUNT_APPROVAL_TIERS, 100_000, "finance_manager"
        )


def test_record_approval_uses_amount_tiers() -> None:
    chain = record_approval(
        None,
        tenant_id=TESTING_TENANT_UUID,
        module_key="team_expenses",
        user_id=1,
        role="manager",
        name="Mgr",
        amount=100,
    )
    assert chain["mode"] == "amount_tier"
    assert quorum_met(chain)
    # Same user again is idempotent
    again = record_approval(
        chain,
        tenant_id=TESTING_TENANT_UUID,
        module_key="team_expenses",
        user_id=1,
        role="manager",
        name="Mgr",
        amount=100,
    )
    assert len(again["approvals"]) == 1


def test_record_approval_blocks_wrong_role() -> None:
    with pytest.raises(ApprovalQuorumForbiddenError):
        record_approval(
            None,
            tenant_id=TESTING_TENANT_UUID,
            module_key="expenses",
            user_id=1,
            role="employee",
            name="Emp",
            amount=100,
        )
