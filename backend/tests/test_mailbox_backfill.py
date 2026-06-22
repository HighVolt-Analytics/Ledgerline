"""Mailbox historical import (date-range backfill)."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.services.email_ingestion import build_historical_inbox_filter
from app.services.mailbox_backfill_service import validate_backfill_dates


def test_build_historical_inbox_filter() -> None:
    filt = build_historical_inbox_filter(date(2026, 1, 1), date(2026, 1, 31))
    assert "receivedDateTime ge 2026-01-01T00:00:00Z" in filt
    assert "receivedDateTime lt 2026-02-01T00:00:00Z" in filt
    assert "hasAttachments eq true" in filt
    assert "isRead" not in filt


def test_validate_backfill_dates_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="End date"):
        validate_backfill_dates(date(2026, 2, 1), date(2026, 1, 1))


def test_validate_backfill_dates_rejects_long_span(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPH_BACKFILL_MAX_DAYS", "30")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="30 days"):
        validate_backfill_dates(date(2026, 1, 1), date(2026, 3, 1))
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_start_backfill_api(client, db_session) -> None:
    from app.models.connected_mailbox import ConnectedMailbox

    reg = await client.post(
        "/api/auth/register",
        json={
            "email": "backfill@example.com",
            "password": "securepass1",
            "full_name": "Backfill User",
            "tenant_name": "Backfill Org",
            "tenant_slug": "backfill-org",
        },
    )
    assert reg.status_code == 201
    reg_body = reg.json()["data"]
    token = reg_body["access_token"]
    tenant_id = reg_body["user"]["org_id"]

    mb = ConnectedMailbox(
        tenant_id=tenant_id,
        email="inbox@company.com",
        display_name="Inbox",
        is_active=True,
        auth_type="delegated",
        connection_status="connected",
        refresh_token_encrypted="enc",
    )
    db_session.add(mb)
    await db_session.flush()

    with patch(
        "app.workers.tasks.mailbox_backfill_task.delay",
        side_effect=RuntimeError("no celery"),
    ):
        res = await client.post(
            f"/api/mailboxes/{mb.id}/backfill",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "from_date": (date.today() - timedelta(days=7)).isoformat(),
                "to_date": date.today().isoformat(),
                "mark_processed": False,
            },
        )

    assert res.status_code == 202
    body = res.json()["data"]
    assert body["job"]["mailbox_id"] == mb.id
    assert body["job"]["status"] in ("queued", "running", "completed")

    status = await client.get(
        f"/api/mailboxes/{mb.id}/backfill/{body['job']['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.status_code == 200
    assert status.json()["data"]["id"] == body["job"]["id"]
