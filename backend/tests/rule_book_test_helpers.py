"""Load rule-book config in tests (async API)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.rule_book_mapper import load_classification_config
from app.tenant_ids import TESTING_TENANT_UUID

_DEMO_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"


def demo_rule_book_payload() -> dict:
    return json.loads(_DEMO_FIXTURE.read_text(encoding="utf-8"))


def demo_rule_book_config() -> RuleBookConfigPayload:
    return validate_rule_book_config_payload(demo_rule_book_payload())


async def load_demo_config_for_tenant(
    db_session: AsyncSession,
    tenant_id: uuid.UUID = TESTING_TENANT_UUID,
) -> RuleBookConfigPayload:
    return await load_classification_config(db_session, tenant_id)


def patch_sync_load_classification_config(
    monkeypatch: pytest.MonkeyPatch,
    config: RuleBookConfigPayload | None = None,
    *,
    module: str = "app.services.rule_book_mapper",
) -> RuleBookConfigPayload:
    """Monkeypatch async load_classification_config for unit tests."""
    cfg = config or demo_rule_book_config()

    async def _load(_session, _tenant_id):
        return cfg

    monkeypatch.setattr(f"{module}.load_classification_config", _load)
    return cfg
