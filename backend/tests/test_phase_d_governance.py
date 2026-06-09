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
from app.services.account_mapper import clear_rule_book_cache
from app.services.auth_service import create_access_token, hash_password
from app.services.rule_book_audit import diff_rule_book_config


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
        template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    res = await client.get("/api/rule-book/config")
    body = res.json()["data"]
    body["vendor_detection_config"] = {
        **body["vendor_detection_config"],
        "threshold": 72,
    }
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
    assert row.org_id == 1
    assert row.detail is not None
    assert "changes" in row.detail
    assert row.detail["after"]["vendor_detection_config"]["threshold"] == 72

    get_settings.cache_clear()
    clear_rule_book_cache()


@pytest.mark.asyncio
async def test_rule_book_changelog_lists_events(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    clear_rule_book_cache()

    body = (await client.get("/api/rule-book/config")).json()["data"]
    body["posting_defaults"] = {
        **body["posting_defaults"],
        "fallback_account": "Suspense 9999",
    }
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
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    clear_rule_book_cache()

    member = User(
        org_id=1,
        email="member@hv.com",
        password_hash=hash_password("memberpass1"),
        full_name="Member User",
        role=UserRole.MEMBER,
    )
    db_session.add(member)
    await db_session.flush()

    token = create_access_token(
        user_id=member.id,
        org_id=1,
        org_slug="hv-org",
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
