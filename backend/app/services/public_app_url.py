"""Public frontend base URL for links in emails and exports."""

from urllib.parse import urlparse

from app.config import get_settings


def resolve_public_app_base_url() -> str:
    """Origin (+ optional basename) for clickable app links."""
    settings = get_settings()
    explicit = settings.public_app_url.strip().rstrip("/")
    if explicit:
        return explicit

    frontend = settings.graph_oauth_frontend_return_url.strip()
    if frontend:
        parsed = urlparse(frontend)
        path = parsed.path.rstrip("/")
        if path and "/" in path.lstrip("/"):
            app_path = path.rsplit("/", 1)[0]
        else:
            app_path = settings.root_path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{app_path}".rstrip("/")

    origins = settings.cors_origin_list
    if origins:
        origin = origins[0].rstrip("/")
        prefix = settings.root_path.rstrip("/")
        return f"{origin}{prefix}" if prefix else origin

    return ""


def build_public_app_path(path: str) -> str:
    """Absolute URL for a frontend route (path must start with /)."""
    base = resolve_public_app_base_url()
    if not path.startswith("/"):
        path = f"/{path}"
    if base:
        return f"{base.rstrip('/')}{path}"
    return path
