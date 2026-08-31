"""Deprecated. Use app.integrations.xero.sync."""

from app.integrations.xero.sync import (  # noqa: F401
    mark_sync_committed,
    sync_contacts,
    sync_settings,
)
