"""Deprecated. Use app.integrations.xero.master_data."""

from app.integrations.xero.master_data import (  # noqa: F401
    get_master_data_totals,
    latest_webhook_at,
    list_export_history,
    list_sync_history,
    list_xero_accounts,
    list_xero_contacts,
    list_xero_tax_rates,
    resolve_selected_xero_tenant_id,
)
