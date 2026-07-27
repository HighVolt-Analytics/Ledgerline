"""Classify Xero / export errors into TRANSIENT / RECOVERABLE / TERMINAL buckets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.integration.xero_client import XeroApiError

ERROR_TRANSIENT = "TRANSIENT"
ERROR_RECOVERABLE = "RECOVERABLE"
ERROR_TERMINAL = "TERMINAL"

_TERMINAL_CODES = {
    "invalid_payload",
    "unsupported_currency",
    "currency_not_supported",
    "currency_missing",
    "currency_not_mapped",
    "invalid_tax_account_combination",
    "insufficient_permission",
    "ambiguous_supplier_match",
    "totals_do_not_reconcile",
    "contact_not_mapped",
    "account_not_mapped",
    "tax_type_not_mapped",
    "tracking_option_missing",
    "missing_organisation",
    "invoice_not_processed",
    "accrec_not_supported",
    "validation_failed",
}

_RECOVERABLE_CODES = {
    "expired_access_token",
    "needs_reauth",
    "organisation_not_synced",
    "stale_contact_mapping",
    "inactive_account_mapping",
    "inactive_tax_mapping",
    "reference_data_missing",
}


@dataclass
class ClassifiedError:
    bucket: str
    code: str
    message: str
    retryable: bool
    details: dict[str, Any] | None = None


def classify_error(
    *,
    code: str | None = None,
    message: str | None = None,
    status_code: int | None = None,
    exc: BaseException | None = None,
) -> ClassifiedError:
    err_code = (code or "").strip() or "export_failed"
    err_message = (message or str(exc) if exc else "Export failed")[:512]
    details: dict[str, Any] | None = None

    if isinstance(exc, XeroApiError):
        status_code = exc.status_code
        err_code = exc.error_code or err_code
        err_message = exc.message[:512]
        details = exc.details

    if status_code in {429, 500, 502, 503, 504} or status_code == 0:
        return ClassifiedError(
            bucket=ERROR_TRANSIENT,
            code=err_code,
            message=err_message,
            retryable=True,
            details=details,
        )
    if err_code in _RECOVERABLE_CODES or status_code == 401:
        return ClassifiedError(
            bucket=ERROR_RECOVERABLE,
            code=err_code if status_code != 401 else "expired_access_token",
            message=err_message,
            retryable=True,
            details=details,
        )
    if err_code in _TERMINAL_CODES or status_code in {400, 403}:
        return ClassifiedError(
            bucket=ERROR_TERMINAL,
            code=err_code,
            message=err_message,
            retryable=False,
            details=details,
        )
    # Default: treat unknown 4xx as terminal, else recoverable.
    if status_code is not None and 400 <= status_code < 500:
        return ClassifiedError(
            bucket=ERROR_TERMINAL,
            code=err_code,
            message=err_message,
            retryable=False,
            details=details,
        )
    return ClassifiedError(
        bucket=ERROR_RECOVERABLE,
        code=err_code,
        message=err_message,
        retryable=True,
        details=details,
    )
