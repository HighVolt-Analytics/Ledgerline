"""Server-side rule book saves commit before HTTP response."""

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
async def test_put_persists_before_response_even_with_debounce(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload-safe: API PUT must not rely on a delayed in-memory flush timer."""
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RULE_BOOK_SAVE_DEBOUNCE_MS", "5000")
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_rule_book_save_buffers()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    body["email_capture_rules"][0]["name"] = "Persisted immediately"
    await client.put("/api/rule-book/config", json=body)

    refreshed = (await client.get("/api/rule-book/config")).json()["data"]
    assert refreshed["email_capture_rules"][0]["name"] == "Persisted immediately"

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "rule_book_updated")
        )
    ).scalars().all()
    assert len(audit_rows) >= 1

    clear_rule_book_save_buffers()
    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_debounced_puts_commit_once_without_request_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Background timer path still coalesces bursts when no request session is passed."""
    from app.schemas.rule_book_config import validate_rule_book_config_payload
    from app.services.rule_book_config_io import load_rule_book_config_dict
    from app.services.rule_book_save_buffer import schedule_rule_book_save

    monkeypatch.setenv("RULE_BOOK_SAVE_DEBOUNCE_MS", "50")
    get_settings.cache_clear()
    clear_rule_book_save_buffers()

    before = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    payload = validate_rule_book_config_payload(before)
    after = payload.model_dump()
    after["email_capture_rules"][0]["name"] = "Timer burst 1"
    payload = validate_rule_book_config_payload(after)
    await schedule_rule_book_save(
        tenant_id=TESTING_TENANT_UUID,
        payload=payload,
        after_raw=payload.model_dump(),
        actor_name=None,
        actor_email=None,
        client_ip=None,
        db=None,
    )

    after["email_capture_rules"][0]["name"] = "Timer burst 2"
    payload = validate_rule_book_config_payload(after)
    await schedule_rule_book_save(
        tenant_id=TESTING_TENANT_UUID,
        payload=payload,
        after_raw=payload.model_dump(),
        actor_name=None,
        actor_email=None,
        client_ip=None,
        db=None,
    )

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
