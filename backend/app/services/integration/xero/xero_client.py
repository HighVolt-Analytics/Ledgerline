"""Deprecated. Use app.integrations.xero.http_legacy (retry client) or app.integrations.xero.client."""

from app.integrations.xero.http_legacy import (  # noqa: F401
    DEFAULT_TIMEOUT,
    XeroApiError,
    XeroClient,
)
