"""Approval policy is stored per tenant in Postgres (not shared demo defaults)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_approval_policy import TenantApprovalPolicy
from app.services.approval.approval_policy_io import (
    clear_approval_policy_cache,
    load_policy_for_tenant_async,
    save_policy_for_tenant_async,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_approval_policy_heals_legacy_rules_only_schema(
    db_session: AsyncSession,
) -> None:
    from app.services.approval.approval_policy_repository import upsert_policy

    clear_approval_policy_cache()
    await upsert_policy(
        db_session,
        TESTING_TENANT_UUID,
        {
            "locked": False,
            "matrix": {"Admin": {"View": True, "Approve": True}},
            "rules": [{"id": "ap1", "approver": "CFO approval"}],
        },
    )
    policy = await load_policy_for_tenant_async(db_session, TESTING_TENANT_UUID)
    assert policy.amount_approval_tiers
    assert policy.amount_approval_tiers[0].approval_1 == "Manager"
    assert "Finance Manager" in policy.matrix

    row = await db_session.get(TenantApprovalPolicy, TESTING_TENANT_UUID)
    assert row is not None
    assert "amount_approval_tiers" in row.config
    assert "rules" not in row.config


@pytest.mark.asyncio
async def test_approval_policy_persists_per_tenant_in_db(
    db_session: AsyncSession,
) -> None:
    clear_approval_policy_cache()
    other_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440099")
    db_session.add(
        Tenant(
            id=other_id,
            name="Other Org",
            slug="other-org-policy",
            currency="AUD",
            settings_json={"country": "AU"},
        )
    )
    await db_session.flush()

    policy_a = await load_policy_for_tenant_async(db_session, TESTING_TENANT_UUID)
    policy_a.matrix["Manager"]["Comment"] = False
    policy_a.amount_approval_tiers[0].approval_1 = "Finance Manager"
    await save_policy_for_tenant_async(db_session, TESTING_TENANT_UUID, policy_a)

    policy_b = await load_policy_for_tenant_async(db_session, other_id)
    assert policy_b.matrix["Manager"]["Comment"] is True
    assert policy_b.amount_approval_tiers[0].approval_1 == "Manager"

    clear_approval_policy_cache()
    reloaded_a = await load_policy_for_tenant_async(db_session, TESTING_TENANT_UUID)
    reloaded_b = await load_policy_for_tenant_async(db_session, other_id)

    assert reloaded_a.matrix["Manager"]["Comment"] is False
    assert reloaded_a.amount_approval_tiers[0].approval_1 == "Finance Manager"
    assert reloaded_b.matrix["Manager"]["Comment"] is True
    assert reloaded_b.amount_approval_tiers[0].approval_1 == "Manager"

    row_a = await db_session.get(TenantApprovalPolicy, TESTING_TENANT_UUID)
    row_b = await db_session.get(TenantApprovalPolicy, other_id)
    assert row_a is not None and row_b is not None
    assert row_a.config["matrix"]["Manager"]["Comment"] is False
    assert row_b.config["matrix"]["Manager"]["Comment"] is True
