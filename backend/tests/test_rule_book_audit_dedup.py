"""Hard guard against duplicate rule_book_updated audit rows."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import log_event
from app.services.rule_book_audit import (
    is_duplicate_rule_book_update,
    log_rule_book_updated,
    normalize_rule_book_for_diff,
)


@pytest.mark.asyncio
async def test_log_rule_book_updated_suppresses_identical_content(
    db_session: AsyncSession,
) -> None:
    config = normalize_rule_book_for_diff(
        {
            "schema_version": 1,
            "email_capture_rules": [
                {
                    "id": "ec-1",
                    "name": "AWS",
                    "enabled": True,
                    "priority": 1,
                    "mailbox": "a@test.com",
                    "root": {"type": "group", "operator": "AND", "children": []},
                    "action": {"save_attachment": True, "route_to": "Inbox"},
                }
            ],
        }
    )

    first = await log_rule_book_updated(
        db_session,
        org_id=1,
        after_config=config,
        detail={"changes": {"email_capture_rules": {"modified": ["ec-1"]}}},
        actor_name="Admin",
    )
    assert first is not None
    await db_session.commit()

    assert await is_duplicate_rule_book_update(db_session, 1, config) is True

    second = await log_rule_book_updated(
        db_session,
        org_id=1,
        after_config=config,
        detail={"changes": {"email_capture_rules": {"modified": ["ec-1"]}}},
        actor_name="Admin",
    )
    assert second is None


@pytest.mark.asyncio
async def test_log_rule_book_updated_allows_real_change(
    db_session: AsyncSession,
) -> None:
    base = normalize_rule_book_for_diff(
        {
            "schema_version": 1,
            "email_capture_rules": [
                {
                    "id": "ec-1",
                    "name": "AWS",
                    "enabled": True,
                    "priority": 1,
                    "mailbox": "a@test.com",
                    "root": {"type": "group", "operator": "AND", "children": []},
                    "action": {"save_attachment": True, "route_to": "Inbox"},
                }
            ],
        }
    )
    changed = normalize_rule_book_for_diff(
        {
            **base,
            "email_capture_rules": [
                {**base["email_capture_rules"][0], "name": "AWS billing"}
            ],
        }
    )

    await log_rule_book_updated(
        db_session,
        org_id=1,
        after_config=base,
        detail={"changes": {}},
    )
    await db_session.commit()

    assert await is_duplicate_rule_book_update(db_session, 1, changed) is False

    row = await log_rule_book_updated(
        db_session,
        org_id=1,
        after_config=changed,
        detail={"changes": {}},
    )
    assert row is not None
