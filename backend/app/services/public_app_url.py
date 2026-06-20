"""Public frontend base URL for links in emails and exports."""

from urllib.parse import urlparse

from app.config import get_settings


def resolve_public_app_base_url() -> str:
    """Origin (+ optional basename) for clickable app links."""
    settings = get_settings()
    explicit = settings.public_app_url.strip().rstrip("/")
    if explicit and "localhost" not in explicit and "127.0.0.1" not in explicit:
        return explicit

    webapp = settings.azure_webapp_url.strip().rstrip("/")
    if webapp:
        return webapp

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


def _base_with_root_path(base: str) -> str:
    """Ensure BASE_PATH is present once on the public app origin (e.g. /ledgerlink)."""
    settings = get_settings()
    prefix = settings.root_path.rstrip("/")
    base = base.rstrip("/")
    if not prefix:
        return base
    if base.endswith(prefix):
        return base
    return f"{base}{prefix}"


def build_public_app_path(path: str) -> str:
    """Absolute URL for a frontend route (path must start with /)."""
    if not path.startswith("/"):
        path = f"/{path}"
    base = resolve_public_app_base_url().strip()
    if base:
        return f"{_base_with_root_path(base)}{path}"
    prefix = get_settings().root_path.rstrip("/")
    return f"{prefix}{path}" if prefix else path
