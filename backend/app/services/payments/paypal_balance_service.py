"""PayPal account balance — never invent balance from transactions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant_payment_provider import (
    PROVIDER_PAYPAL,
    TenantPaymentProviderAccount,
)
from app.services.payments.paypal_client import PaypalApiError, get_paypal_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

REPORTING_ACCESS_REQUIRED = "paypal_reporting_access_required"


class PaypalBalanceError(Exception):
    """PayPal balance service error."""


def _unavailable(reason: str = REPORTING_ACCESS_REQUIRED) -> dict[str, Any]:
    return {"available": False, "reason": reason, "balances": []}


async def get_paypal_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantPaymentProviderAccount | None:
    return (
        await db.execute(
            select(TenantPaymentProviderAccount).where(
                TenantPaymentProviderAccount.tenant_id == tenant_id,
                TenantPaymentProviderAccount.provider == PROVIDER_PAYPAL,
                TenantPaymentProviderAccount.status != "disconnected",
            )
        )
    ).scalar_one_or_none()


async def get_paypal_balance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Return real PayPal balances when enabled and visible; else capability denial."""
    settings = get_settings()
    if not settings.paypal_configured:
        return _unavailable("paypal_not_configured")
    if not settings.paypal_balance_enabled:
        return _unavailable(REPORTING_ACCESS_REQUIRED)

    account = await get_paypal_account(db, tenant_id)
    if account is None or not account.balance_visibility:
        return _unavailable(REPORTING_ACCESS_REQUIRED)

    merchant_id = (
        (account.provider_merchant_id or account.provider_account_id or "").strip()
    )
    if not merchant_id:
        return _unavailable(REPORTING_ACCESS_REQUIRED)

    client = get_paypal_client()
    try:
        # Official Reporting Balances API (requires approved reporting access).
        payload = await client.request_json(
            "GET",
            "/v1/reporting/balances",
            params={
                "currency_code": (account.default_currency or "AUD").upper(),
                "as_of_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
    except PaypalApiError as exc:
        logger.warning(
            "paypal_balance_fetch_failed",
            tenant_id=str(tenant_id),
            status_code=exc.status_code,
            error_code=exc.error_code,
        )
        account.last_error_code = exc.error_code
        account.last_error_message = str(exc)[:512]
        await db.flush()
        return _unavailable(REPORTING_ACCESS_REQUIRED)

    balances: list[dict[str, Any]] = []
    for row in payload.get("balances") or []:
        if not isinstance(row, dict):
            continue
        total = row.get("total_balance") or {}
        available = row.get("available_balance") or {}
        balances.append(
            {
                "currency": total.get("currency_code") or available.get("currency_code"),
                "total": total.get("value"),
                "available": available.get("value"),
                "primary": bool(row.get("primary")),
            }
        )

    account.last_balance_sync_at = datetime.now(timezone.utc)
    account.last_error_code = None
    account.last_error_message = None
    await db.flush()

    return {
        "available": True,
        "reason": None,
        "balances": balances,
        "merchant_id": merchant_id,
        "as_of": payload.get("as_of_time") or payload.get("last_refresh_time"),
    }
