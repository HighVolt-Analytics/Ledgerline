
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Phase D — rule book governance (audit trail + admin permissions)."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.rule_book.rule_book_audit import (
    diff_rule_book_config,
    rule_book_changes_are_auditable,
    truly_modified_rule_ids,
)


def test_rule_book_changes_are_auditable() -> None:
    config = {
        "email_capture_rules": [
            {"id": "ec-1", "name": "AWS", "enabled": True, "priority": 1},
        ],
        "purchase_rules": [],
    }
    assert not rule_book_changes_are_auditable({}, before=config, after=config)
    assert not rule_book_changes_are_auditable(
        {"email_capture_rules": {"added": [], "removed": [], "modified": []}},
        before=config,
        after=config,
    )
    assert rule_book_changes_are_auditable(
        {"email_capture_rules": {"added": ["ec-2"], "removed": [], "modified": []}},
        before=config,
        after={
            **config,
            "email_capture_rules": [
                *config["email_capture_rules"],
                {"id": "ec-2", "name": "New", "enabled": True, "priority": 2},
            ],
        },
    )
    assert not rule_book_changes_are_auditable(
        {
            "vendor_detection_config": {
                "before": {"threshold": 70},
                "after": {"threshold": 72},
            }
        },
        before=config,
        after=config,
    )


def test_spurious_modified_rule_ids_suppressed() -> None:
    rule = {
        "id": "ec-1",
        "name": "AWS billing",
        "enabled": True,
        "priority": 1,
        "mailbox": "accounts@test.com",
        "root": {"type": "group", "operator": "AND", "children": []},
        "action": {"save_attachment": True, "route_to": "Inbox"},
        "matched_count": 1,
        "last_matched": "1h ago",
    }
    before = {"email_capture_rules": [rule]}
    after_rule = {**rule, "matched_count": 99, "last_matched": "now"}
    after = {"email_capture_rules": [after_rule]}
    assert truly_modified_rule_ids("email_capture_rules", before, after, ["ec-1"]) == []
    assert not rule_book_changes_are_auditable(
        {
            "email_capture_rules": {
                "added": [],
                "removed": [],
                "modified": ["ec-1"],
            }
        },
        before=before,
        after=after,
    )


def test_diff_rule_book_config_tracks_rule_ids() -> None:
    before = {
        "email_capture_rules": [
            {"id": "ec-1", "name": "AWS", "enabled": True, "priority": 1},
        ],
        "purchase_rules": [],
    }
    after = {
        "email_capture_rules": [
            {"id": "ec-1", "name": "AWS billing", "enabled": True, "priority": 1},
            {"id": "ec-2", "name": "New rule", "enabled": True, "priority": 2},
        ],
        "purchase_rules": [],
    }
    changes = diff_rule_book_config(before, after)
    assert "ec-2" in changes["email_capture_rules"]["added"]
    assert "ec-1" in changes["email_capture_rules"]["modified"]


@pytest.mark.asyncio
async def test_rule_book_put_writes_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(get_settings().rule_book_config_path)
    if not template.is_file():
        template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    res = await client.get("/api/rule-book/config")
    body = res.json()["data"]
    body["email_capture_rules"][0]["name"] = "AWS billing (updated)"
    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 200

    row = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event == "rule_book_updated")
            .order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert row is not None
    assert row.tenant_id == TESTING_TENANT_UUID
    assert row.detail is not None
    assert "changes" in row.detail
    assert "ec-1" in row.detail["changes"]["email_capture_rules"]["modified"]

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_rule_book_put_noop_does_not_write_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 200

    body = (await client.get("/api/rule-book/config")).json()["data"]
    before_count = len(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event == "rule_book_updated")
            )
        ).scalars().all()
    )

    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 200

    after_count = len(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.event == "rule_book_updated")
            )
        ).scalars().all()
    )
    assert after_count == before_count

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_rule_book_changelog_lists_events(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    body["purchase_rules"][0]["name"] = "PO prefix match (updated)"
    await client.put("/api/rule-book/config", json=body)

    res = await client.get("/api/rule-book/changelog?limit=5")
    assert res.status_code == 200
    events = [row["event"] for row in res.json()["data"]]
    assert "rule_book_updated" in events

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_member_cannot_put_rule_book_when_auth_required(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    clear_rule_book_cache()

    member = User(
        tenant_id=TESTING_TENANT_UUID,
        email="member@hv.com",
        password_hash=hash_password("memberpass1"),
        full_name="Member User",
        role=UserRole.MEMBER,
    )
    db_session.add(member)
    await db_session.flush()

    token = create_access_token(
        user_id=member.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        email=member.email,
        role=member.role.value,
    )
    body = json.loads(template.read_text(encoding="utf-8"))
    res = await client.put(
        "/api/rule-book/config",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403

    get_settings.cache_clear()
    clear_rule_book_cache()
