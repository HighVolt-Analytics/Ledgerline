"""Microsoft 365 OAuth mailbox connection tests."""

from datetime import datetime, timezone

import jwt
import pytest

from app.config import get_settings
from app.models.connected_mailbox import AUTH_DELEGATED, ConnectedMailbox
from app.services.mailbox_oauth_service import (
    complete_oauth_callback,
    create_oauth_state,
    parse_oauth_state,
    resolve_delegated_access_token,
)
from app.services.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID, parse_tenant_id
from tests.auth_test_helpers import seed_admin_user


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GRAPH_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/oauth/callback",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_oauth_state_roundtrip() -> None:
    state = create_oauth_state(tenant_id=TESTING_TENANT_UUID, user_id=7)
    payload = parse_oauth_state(state)
    assert parse_tenant_id(payload["org_id"]) == TESTING_TENANT_UUID
    assert payload["user_id"] == 7
    assert payload["typ"] == "mailbox_oauth"


def test_oauth_state_rejects_tampering() -> None:
    state = create_oauth_state(tenant_id=TESTING_TENANT_UUID, user_id=7)
    bad = f"{state}tampered"
    with pytest.raises(jwt.PyJWTError):
        parse_oauth_state(bad)


def test_token_vault_roundtrip() -> None:
    secret = "refresh-token-value-123"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret


@pytest.mark.asyncio
async def test_resolve_delegated_access_token_uses_cached_access() -> None:
    mailbox = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="user@example.com",
        auth_type=AUTH_DELEGATED,
        connection_status="connected",
        access_token_encrypted=encrypt_secret("access-token"),
        refresh_token_encrypted=encrypt_secret("refresh-token"),
        token_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    assert await resolve_delegated_access_token(mailbox) == "access-token"


@pytest.mark.asyncio
async def test_complete_oauth_callback_rejects_invalid_user(db_session) -> None:
    state = create_oauth_state(tenant_id=TESTING_TENANT_UUID, user_id=999_999)
    with pytest.raises(RuntimeError, match="OAuth session invalid"):
        await complete_oauth_callback(
            db_session,
            code="unused-code",
            state=state,
        )


@pytest.mark.asyncio
async def test_mailbox_oauth_callback_sanitizes_internal_errors(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("secret internal token failure")

    monkeypatch.setattr(
        "app.api.mailboxes.complete_oauth_callback",
        _boom,
    )
    state = create_oauth_state(tenant_id=TESTING_TENANT_UUID, user_id=1)
    res = await client.get(
        "/api/mailboxes/oauth/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    location = res.headers.get("location", "")
    assert "mailbox_oauth=error" in location
    assert "secret internal" not in location
    assert "Mailbox+connection+failed" in location or "Mailbox%20connection%20failed" in location


@pytest.mark.asyncio
async def test_mailbox_oauth_authorize_requires_auth(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    res = await client.get("/api/mailboxes/oauth/authorize")
    assert res.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mailbox_oauth_authorize_returns_url(client, db_session) -> None:
    _, token = await seed_admin_user(
        db_session, email="admin@acme.com", tenant_slug="hv-org", full_name="Admin"
    )
    await db_session.commit()
    res = await client.get(
        "/api/mailboxes/oauth/authorize",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert "invitation" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mailbox_oauth_callback_does_not_require_auth(client) -> None:
    """Microsoft redirect must not hit require_user (401)."""
    state = create_oauth_state(tenant_id=TESTING_TENANT_UUID, user_id=1)
    res = await client.get(
        "/api/mailboxes/oauth/callback",
        params={"code": "invalid-code", "state": state},
        follow_redirects=False,
    )
    assert res.status_code != 401
    assert res.status_code in (302, 307)
    location = res.headers.get("location", "")
    assert "mailbox_oauth=error" in location


@pytest.mark.asyncio
async def test_direct_add_mailbox_blocked_when_oauth_configured(client, db_session) -> None:
    _, token = await seed_admin_user(
        db_session, email="admin2@acme.com", tenant_slug="hv-org", full_name="Admin"
    )
    await db_session.commit()
    res = await client.post(
        "/api/mailboxes",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "silent@example.com"},
    )
    assert res.status_code == 422
