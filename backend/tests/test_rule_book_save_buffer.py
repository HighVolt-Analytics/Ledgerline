"""Server-side debounced rule book saves."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.services.account_mapper import clear_rule_book_cache
from app.services.rule_book_save_buffer import (
    clear_rule_book_save_buffers,
    flush_rule_book_save_buffer,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_debounced_puts_commit_once(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RULE_BOOK_SAVE_DEBOUNCE_MS", "50")
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_rule_book_save_buffers()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    body["email_capture_rules"][0]["name"] = "Burst edit 1"
    await client.put("/api/rule-book/config", json=body)
    body["email_capture_rules"][0]["name"] = "Burst edit 2"
    await client.put("/api/rule-book/config", json=body)
    body["email_capture_rules"][0]["name"] = "Burst edit 3"
    await client.put("/api/rule-book/config", json=body)

    before_flush = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "rule_book_updated")
        )
    ).scalars().all()
    assert len(before_flush) == 0

    await flush_rule_book_save_buffer(TESTING_TENANT_UUID, db=db_session)
    await db_session.commit()

    after_flush = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "rule_book_updated")
        )
    ).scalars().all()
    assert len(after_flush) == 1

    clear_rule_book_save_buffers()
    get_settings.cache_clear()
    clear_rule_book_cache()
