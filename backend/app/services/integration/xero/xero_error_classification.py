"""Deprecated. Use app.integrations.xero.errors."""

from app.integrations.xero.errors import (  # noqa: F401
    ERROR_RECOVERABLE,
    ERROR_TERMINAL,
    ERROR_TRANSIENT,
    ClassifiedError,
    classify_error,
)
