"""Legacy rule book file import mapping."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_legacy_int_file_imports_to_testing_tenant(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_books = tmp_path / "rule_books"
    rule_books.mkdir(parents=True)
    template = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    legacy = json.loads(template.read_text(encoding="utf-8"))
    legacy["purchase_rules"] = [
        {
            "id": "legacy-import",
            "name": "Legacy",
            "enabled": True,
            "priority": 1,
            "match": {"type": "group", "operator": "AND", "children": []},
            "post_to": {"ledger": "Legacy Ledger", "sub_ledger": ""},
        }
    ]
    (rule_books / "1_config.json").write_text(json.dumps(legacy), encoding="utf-8")

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    row = await db_session.get(TenantRuleBookConfig, TESTING_TENANT_UUID)
    if row:
        await db_session.delete(row)
        await db_session.flush()

    loaded = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    assert any(r.get("id") == "legacy-import" for r in loaded.get("purchase_rules", []))

    stored = (
        await db_session.execute(
            select(TenantRuleBookConfig).where(
                TenantRuleBookConfig.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one_or_none()
    assert stored is not None
