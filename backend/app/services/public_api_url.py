"""Public HTTPS base URL for Meta webhooks and OAuth callbacks."""

from urllib.parse import urlparse

from app.config import get_settings


def resolve_public_api_base_url() -> str:
    """Origin for webhook + OAuth callback (ngrok or Azure App Service)."""
    settings = get_settings()
    tunnel = settings.public_tunnel_url.strip().rstrip("/")
    if tunnel:
        return tunnel

    redirect = settings.whatsapp_oauth_redirect_uri.strip()
    if redirect:
        parsed = urlparse(redirect)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    mailbox_redirect = settings.graph_oauth_redirect_uri.strip()
    if mailbox_redirect:
        parsed = urlparse(mailbox_redirect)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    if settings.azure_webapp_url.strip():
        return settings.azure_webapp_url.strip().rstrip("/")

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
