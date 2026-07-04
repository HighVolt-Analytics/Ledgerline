"""Public HTTPS base URL for Meta webhooks and OAuth callbacks."""

from urllib.parse import urlparse

import httpx

from app.config import get_settings

_OAUTH_CALLBACK_SUFFIXES = (
    "/auth/whatsapp/callback",
    "/api/auth/whatsapp/callback",
)


def _base_from_redirect_url(redirect: str) -> str | None:
    """Derive public app base including path prefix (e.g. /ledgerlink)."""
    parsed = urlparse(redirect.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    path = (parsed.path or "").rstrip("/")
    for suffix in _OAUTH_CALLBACK_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if path:
        return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def resolve_public_api_base_url() -> str:
    """Origin for webhook + OAuth callback (ngrok or Azure App Service)."""
    settings = get_settings()
    tunnel = settings.public_tunnel_url.strip().rstrip("/")
    if tunnel:
        return tunnel

    if settings.azure_webapp_url.strip():
        return settings.azure_webapp_url.strip().rstrip("/")

    redirect = settings.whatsapp_oauth_redirect_uri.strip()
    if redirect:
        base = _base_from_redirect_url(redirect)
        if base:
            return base

    mailbox_redirect = settings.graph_oauth_redirect_uri.strip()
    if mailbox_redirect:
        parsed = urlparse(mailbox_redirect)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    return "http://localhost:8001"


def webhook_meta_url() -> str:
    return f"{resolve_public_api_base_url()}/webhook/meta"


def webhook_viber_url() -> str:
    settings = get_settings()
    explicit = settings.viber_webhook_url.strip().rstrip("/")
    if explicit:
        return explicit
    return f"{resolve_public_api_base_url()}/webhook/viber"


async def probe_public_webhook(url: str, *, timeout: float = 8.0) -> tuple[bool, str | None]:
    """
    Check whether a public webhook URL is reachable (ngrok tunnel up, returns JSON).

    Returns (reachable, error_hint). Uses ngrok-skip-browser-warning for free-tier tunnels.
    """
    target = url.strip().rstrip("/")
    if not target:
        return False, "Webhook URL is empty"
    if target.startswith("http://localhost") or target.startswith("http://127.0.0.1"):
        return False, "Webhook URL is localhost — Viber cannot reach it. Start ngrok and set PUBLIC_TUNNEL_URL."

    headers = {"ngrok-skip-browser-warning": "1"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(target, headers=headers)
            body_preview = (response.text or "")[:500]
            if response.status_code != 200:
                if "ERR_NGROK" in body_preview or "is offline" in body_preview.lower():
                    return False, "ngrok tunnel is offline — run: ngrok http 8001, then update PUBLIC_TUNNEL_URL in .env and restart the API"
                return False, f"Webhook returned HTTP {response.status_code}"
            try:
                payload = response.json()
            except ValueError:
                return False, "Webhook did not return JSON (ngrok browser warning or wrong port)"
            if isinstance(payload, dict) and payload.get("status") == 0:
                return True, None
            return False, f"Unexpected webhook response: {payload!r}"
    except httpx.RequestError as exc:
        return False, f"Could not reach webhook URL: {exc}"


def whatsapp_oauth_callback_url() -> str:
    """OAuth redirect URI — must match Meta app registration and token exchange."""
    settings = get_settings()
    explicit = settings.whatsapp_oauth_redirect_uri.strip().rstrip("/")
    tunnel = settings.public_tunnel_url.strip().rstrip("/")
    if tunnel and (
        not explicit
        or "localhost" in explicit
        or "127.0.0.1" in explicit
    ):
        return f"{tunnel}/auth/whatsapp/callback"
    if explicit:
        return explicit
    return f"{resolve_public_api_base_url()}/auth/whatsapp/callback"
