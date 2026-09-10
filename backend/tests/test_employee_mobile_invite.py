"""Invite-to-mobile emails existing Team members the sign-in deep link."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.master_data import EmployeeMasterCreate
from app.services.auth.auth_email_service import (
    InviteEmailResult,
    send_employee_mobile_access_email,
)
from app.services.master_data.master_data_service import create_employee_master
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user


@pytest.fixture(autouse=True)
def _public_app_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:8001")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mobile_access_email_uses_sign_in_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()

    captured: list[dict] = []

    def _fake_deliver(**kwargs):
        captured.append(kwargs)
        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.auth.auth_email_service._deliver_tenant_invite_sync",
        _fake_deliver,
    )

    result = await send_employee_mobile_access_email(
        to_email="member@acme.example.com",
        tenant_name="Acme",
        sign_in_url="http://localhost:8001/login?returnTo=%2Fm",
    )
    assert result.sent is True
    assert len(captured) == 1
    assert "already have a Team login" in captured[0]["body_text"]
    assert "login?returnTo=%2Fm" in captured[0]["body_text"]
    assert "expires in 7 days" not in captured[0]["body_text"].lower()


@pytest.mark.asyncio
async def test_invite_mobile_emails_existing_member(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    async def _fake_access_email(**kwargs):
        captured.append(kwargs)
        return InviteEmailResult(sent=True)

    async def _should_not_invite(**kwargs):
        raise AssertionError("fresh invite email should not be used for existing members")

    monkeypatch.setattr(
        "app.api.employee_masters.send_employee_mobile_access_email",
        _fake_access_email,
    )
    monkeypatch.setattr(
        "app.api.employee_masters.send_tenant_invite_email",
        _should_not_invite,
    )

    _, token = await seed_admin_user(
        db_session,
        email="admin@mobile-invite.example.com",
        tenant_slug="hv-org",
        full_name="Mobile Invite Admin",
    )
    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            name="Admin As Employee",
            email="admin@mobile-invite.example.com",
            status="Active",
        ),
    )
    await db_session.commit()

    invite_res = await client.post(
        f"/api/employee-masters/{employee.id}/invite-mobile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invite_res.status_code == 200, invite_res.text
    body = invite_res.json()["data"]
    assert body["already_member"] is True
    assert body["email_sent"] is True
    assert "returnTo" in (body.get("accept_url") or "")
    assert len(captured) == 1
    assert captured[0]["to_email"] == "admin@mobile-invite.example.com"
    assert "/m" in captured[0]["sign_in_url"] or "%2Fm" in captured[0]["sign_in_url"]
