"""Microsoft Graph API client (application permissions)."""

import base64
import time
from typing import Any

import httpx
import msal

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]

_token_cache: dict[str, Any] = {"expires_at": 0.0, "token": ""}


def _is_configured() -> bool:
    s = get_settings()
    return bool(s.azure_tenant_id and s.azure_client_id and s.azure_client_secret and s.graph_mailbox)


def get_access_token() -> str:
    """Acquire app-only token with in-memory cache."""
    if not _is_configured():
        raise RuntimeError("Microsoft Graph is not configured")

    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

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

    _token_cache["token"] = result["access_token"]
    _token_cache["expires_at"] = now + int(result.get("expires_in", 3600))
    return _token_cache["token"]


def graph_request(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call Graph REST API and return JSON body."""
    token = get_access_token()
    url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}

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
        if response.status_code == 204:
            return {}
        return response.json()


def is_graph_enabled() -> bool:
    return _is_configured()
