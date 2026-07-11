"""Patch accounting_integration_service.py for config consolidation."""

from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app" / "services" / "integration" / "accounting_integration_service.py"
text = p.read_text(encoding="utf-8")

old_import = """from app.services.integration.xero_settings import (
    xero_authorize_url,
    xero_connections_url,
    xero_scopes,
    xero_token_url,
)"""

if old_import in text:
    text = text.replace(old_import, "")

if "def resolve_xero_scopes()" not in text:
    text = text.replace(
        """def xero_configured() -> bool:
    settings = get_settings()
    return bool(settings.xero_client_id.strip() and settings.xero_client_secret.strip())""",
        """def xero_configured() -> bool:
    return get_settings().xero_configured


def resolve_xero_scopes() -> str:
    scopes = get_settings().xero_scopes_resolved
    if not scopes:
        raise ValueError("XERO_SCOPES must be configured")
    return scopes""",
    )

text = text.replace(
    """def build_xero_authorize_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id.strip(),
        "redirect_uri": settings.xero_redirect_uri.strip(),
        "scope": xero_scopes(),
        "state": state,
    }
    return f"{xero_authorize_url()}?{urlencode(params)}"
""",
    """def build_xero_authorize_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id.strip(),
        "redirect_uri": settings.xero_redirect_uri.strip(),
        "scope": resolve_xero_scopes(),
        "state": state,
    }
    return f"{settings.xero_authorize_url}?{urlencode(params)}"
""",
)

text = text.replace("xero_connections_url()", "get_settings().xero_connections_url")
text = text.replace("xero_token_url()", "get_settings().xero_token_url")
text = text.replace("xero_scopes()", "resolve_xero_scopes()")

if "cancel_pending_jobs" not in text:
    disconnect_old = """    row.last_error = None
    row.last_error_code = None
    await db.flush()
    return row


async def _upsert_xero_connections("""
    disconnect_new = """    row.last_error = None
    row.last_error_code = None
    row.last_successful_sync_at = None
    row.token_version = 0
    row.last_refresh_at = None

    from app.services.integration.xero_sync_job_service import cancel_pending_jobs

    await cancel_pending_jobs(db, tenant_id=tenant_id)
    await db.flush()
    return row


async def _upsert_xero_connections("""
    if disconnect_old in text:
        text = text.replace(disconnect_old, disconnect_new)

p.write_text(text, encoding="utf-8")
print("accounting_integration_service.py patched")
