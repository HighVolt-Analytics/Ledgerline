"""Mailbox connection invite flow (admin email → public OAuth)."""

import pytest

from app.config import get_settings
from app.services.mailbox_invite_service import create_invite_token
from app.services.mailbox_oauth_service import create_oauth_state
from app.tenant_ids import parse_tenant_id


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GRAPH_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/oauth/callback",
    )
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_invite_email(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ok(**_kwargs):
        from app.services.mailbox_invite_service import InviteEmailResult

        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.mailbox_invite_service.send_invite_email",
        _ok,
    )


async def _register_admin(client) -> str:
    reg = await client.post(
        "/api/auth/register",
        json={
            "email": "admin@invite.example.com",
            "password": "securepass1",
            "full_name": "Invite Admin",
            "tenant_name": "Invite Org",
            "tenant_slug": "invite-org",
        },
    )
    assert reg.status_code == 201
    return reg.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_create_mailbox_invite(client, mock_invite_email) -> None:
    token = await _register_admin(client)
    res = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "owner@company.com",
            "display_name": "Owner",
            "message": "Please connect your inbox.",
        },
    )
    assert res.status_code == 201
    body = res.json()["data"]
    assert body["requested_email"] == "owner@company.com"
    assert body["status"] == "pending"
    assert body["email_sent"] is True
    assert body["connect_url"].startswith("http")


@pytest.mark.asyncio
async def test_create_mailbox_invite_rejects_duplicate(client, mock_invite_email) -> None:
    token = await _register_admin(client)
    payload = {"email": "dup@company.com"}
    first = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert second.status_code == 422
    assert "pending invitation" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_preview_and_authorize_invite(client, mock_invite_email) -> None:
    token = await _register_admin(client)
    create = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "preview@company.com"},
    )
    assert create.status_code == 201
    request_id = create.json()["data"]["id"]
    tenant_id = parse_tenant_id(create.json()["data"]["org_id"])
    assert tenant_id is not None
    invite_token = create_invite_token(request_id=request_id, tenant_id=tenant_id)

    preview = await client.get(
        "/api/mailboxes/invites/preview",
        params={"token": invite_token},
    )
    assert preview.status_code == 200
    data = preview.json()["data"]
    assert data["requested_email"] == "preview@company.com"
    assert data["tenant_name"]

    authorize = await client.get(
        "/api/mailboxes/invites/authorize",
        params={"token": invite_token},
    )
    assert authorize.status_code == 200
    url = authorize.json()["data"]["authorize_url"]
    assert "login.microsoftonline.com" in url
    assert "client_id=client-id" in url


@pytest.mark.asyncio
async def test_list_and_resend_mailbox_invites(client, mock_invite_email) -> None:
    token = await _register_admin(client)
    create = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "resend@company.com"},
    )
    assert create.status_code == 201
    request_id = create.json()["data"]["id"]

    listing = await client.get(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert any(r["id"] == request_id for r in rows)

    resend = await client.post(
        f"/api/mailboxes/requests/{request_id}/resend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resend.status_code == 200
    assert resend.json()["data"]["status"] == "pending"


@pytest.mark.asyncio
async def test_create_invite_succeeds_when_email_fails(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _register_admin(client)

    def _fail_email(**_kwargs):
        from app.services.mailbox_invite_service import InviteEmailResult

        return InviteEmailResult(sent=False, error="Graph denied")

    monkeypatch.setattr(
        "app.services.mailbox_invite_service.send_invite_email",
        _fail_email,
    )
    res = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "manual@company.com"},
    )
    assert res.status_code == 201
    body = res.json()["data"]
    assert body["email_sent"] is False
    assert body["email_error"] == "Graph denied"
    assert "connect-mailbox?token=" in body["connect_url"]


@pytest.mark.asyncio
async def test_get_invite_link(client, mock_invite_email) -> None:
    token = await _register_admin(client)
    create = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "link@company.com"},
    )
    request_id = create.json()["data"]["id"]
    link = await client.get(
        f"/api/mailboxes/requests/{request_id}/link",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert link.status_code == 200
    assert "connect-mailbox?token=" in link.json()["data"]["connect_url"]


@pytest.mark.asyncio
async def test_invite_oauth_error_redirects_to_connect_mailbox(
    client, mock_invite_email
) -> None:
    token = await _register_admin(client)
    create = await client.post(
        "/api/mailboxes/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "oauth-error@company.com"},
    )
    assert create.status_code == 201
    body = create.json()["data"]
    tenant_id = parse_tenant_id(body["org_id"])
    assert tenant_id is not None
    state = create_oauth_state(tenant_id=tenant_id, invite_request_id=body["id"])

    res = await client.get(
        "/api/mailboxes/oauth/callback",
        params={
            "error": "access_denied",
            "error_description": "Need admin approval",
            "state": state,
        },
        follow_redirects=False,
    )
    assert res.status_code in (302, 307)
    location = res.headers.get("location", "")
    assert "connect-mailbox" in location
    assert "token=" in location
    assert "mailbox_oauth=error" in location
    assert "Need+admin+approval" in location or "Need%20admin%20approval" in location


@pytest.mark.asyncio
async def test_create_invite_requires_signed_in_admin(client, mock_invite_email) -> None:
    res = await client.post(
        "/api/mailboxes/requests",
        json={"email": "anon@company.com"},
    )
    assert res.status_code == 401
