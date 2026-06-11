"""Public HTTPS base URL for Meta webhooks and OAuth callbacks."""

from urllib.parse import urlparse

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
