"""Deprecated. Use app.integrations.xero.mapping."""

from app.integrations.xero.mapping import (  # noqa: F401
    XeroMappingValidationError,
    XeroMappingValidationResult,
    find_xero_contact_id,
    validate_invoice_xero_mappings,
)
