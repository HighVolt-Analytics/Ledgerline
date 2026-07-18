"""Microsoft Graph API client (application + delegated permissions)."""

import time
from typing import Any

import httpx
import msal

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]
# Keep message IDs stable across folder moves — without this, Graph issues a new
# id on move and Exceptions-folder re-poll re-ingests the same attachment.
GRAPH_IMMUTABLE_ID_PREFER = 'IdType="ImmutableId"'

_app_token_cache: dict[str, Any] = {"expires_at": 0.0, "token": ""}


def graph_credentials_configured() -> bool:
    return get_settings().graph_credentials_configured


def is_graph_enabled() -> bool:
    return get_settings().graph_enabled


def get_application_access_token() -> str:
    """Acquire app-only token with in-memory cache."""
    if not graph_credentials_configured():
        raise RuntimeError("Microsoft Graph is not configured")

    now = time.time()
    if _app_token_cache["token"] and now < _app_token_cache["expires_at"] - 60:
        return _app_token_cache["token"]

    settings = get_settings()
    app = msal.ConfidentialClientApplication(
        settings.azure_client_id,
        authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        client_credential=settings.azure_client_secret,
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error") or "unknown"
        raise RuntimeError(f"Graph token failed: {error}")

    _app_token_cache["token"] = result["access_token"]
    _app_token_cache["expires_at"] = now + int(result.get("expires_in", 3600))
    return _app_token_cache["token"]


def get_access_token() -> str:
    """Backward-compatible alias for application token."""
    return get_application_access_token()


def graph_request(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Call Graph REST API and return JSON body."""
    token = access_token or get_application_access_token()
    url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": GRAPH_IMMUTABLE_ID_PREFER,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.request(method, url, headers=headers, params=params, json=json_body)
        if response.is_error:
            logger.error(
                "graph_request_failed",
                status=response.status_code,
                path=path,
                body=response.text[:500],
            )
        response.raise_for_status()
        if response.status_code in (202, 204) or not response.content.strip():
            return {}
        return response.json()
