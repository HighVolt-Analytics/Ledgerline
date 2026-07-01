"""Map service-layer exceptions to HTTP responses."""

from __future__ import annotations

from fastapi import HTTPException

from app.services.vendor_payout_method_service import VendorPayoutMethodError


def http_not_found(exc: LookupError) -> HTTPException:
    return HTTPException(404, str(exc))


def http_bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(400, str(exc))


def http_conflict_or_bad_request(exc: ValueError) -> HTTPException:
    message = str(exc)
    status = 409 if "already exists" in message.lower() else 400
    return HTTPException(status, message)


def http_forbidden(exc: ValueError) -> HTTPException:
    return HTTPException(403, str(exc))


def http_payout_method_error(exc: VendorPayoutMethodError) -> HTTPException:
    return HTTPException(400, str(exc))
