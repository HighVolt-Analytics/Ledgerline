"""Tenant rule book config repository tests."""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.services.rule_book_config_repository import (
    ensure_default_config,
    fetch_config_dict,
    upsert_config,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_ensure_default_and_upsert_roundtrip(db_session: AsyncSession) -> None:
    tid = TESTING_TENANT_UUID
    created = await ensure_default_config(db_session, tid)
    assert isinstance(created, dict)
    assert "schema_version" in created

    created["purchase_rules"] = [{"id": "p1", "name": "Test", "enabled": True, "priority": 1, "match": {"type": "group", "operator": "AND", "children": []}, "post_to": {"ledger": "Office Supplies", "sub_ledger": ""}}]
    await upsert_config(db_session, tid, created, updated_by_user_id=None)

    loaded = await fetch_config_dict(db_session, tid)
    assert loaded is not None
    assert loaded["purchase_rules"][0]["id"] == "p1"


@pytest.mark.asyncio
async def test_ensure_default_is_idempotent(db_session: AsyncSession) -> None:
    first = await ensure_default_config(db_session, TESTING_TENANT_UUID)
    second = await ensure_default_config(db_session, TESTING_TENANT_UUID)
    assert first == second
