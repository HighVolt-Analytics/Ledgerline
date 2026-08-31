"""Deprecated. Use app.integrations.xero.contacts."""

from app.integrations.xero.contacts import (  # noqa: F401
    ContactMatch,
    create_xero_supplier_contact,
    resolve_supplier_contact,
    save_supplier_contact_mapping,
)
