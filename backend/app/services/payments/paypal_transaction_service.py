"""PayPal Transaction Search sync into provider_transactions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant_payment_provider import (
    PROVIDER_PAYPAL,
    ProviderTransaction,
    TenantPaymentProviderAccount,
)
from app.services.payments.paypal_account_service import get_paypal_account_for_tenant
from app.services.payments.paypal_client import PaypalApiError, get_paypal_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

REPORTING_ACCESS_REQUIRED = "paypal_reporting_access_required"


class PaypalTransactionError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def list_paypal_transactions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
    sync: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.paypal_configured:
        return {
            "available": False,
            "reason": "paypal_not_configured",
            "transactions": [],
            "page": page,
            "page_size": page_size,
        }
    if not settings.paypal_transaction_search_enabled:
        return {
            "available": False,
            "reason": REPORTING_ACCESS_REQUIRED,
            "transactions": [],
            "page": page,
            "page_size": page_size,
        }

    account = await get_paypal_account_for_tenant(db, tenant_id)
    if account is None or not account.transactions_visibility:
        return {
            "available": False,
            "reason": REPORTING_ACCESS_REQUIRED,
            "transactions": [],
            "page": page,
            "page_size": page_size,
        }

    if sync:
        try:
            await sync_paypal_transactions(
                db,
                tenant_id,
                account=account,
                start_date=start_date,
                end_date=end_date,
            )
        except PaypalTransactionError as exc:
            logger.warning(
                "paypal_transaction_sync_failed",
                tenant_id=str(tenant_id),
                code=exc.code,
            )
            return {
                "available": False,
                "reason": REPORTING_ACCESS_REQUIRED,
                "transactions": [],
                "page": page,
                "page_size": page_size,
            }

    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    offset = (page - 1) * page_size

    stmt = (
        select(ProviderTransaction)
        .where(
            ProviderTransaction.tenant_id == tenant_id,
            ProviderTransaction.provider == PROVIDER_PAYPAL,
        )
        .order_by(ProviderTransaction.occurred_at.desc().nullslast())
        .offset(offset)
        .limit(page_size)
    )
    if start_date is not None:
        stmt = stmt.where(ProviderTransaction.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(ProviderTransaction.occurred_at <= end_date)

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "available": True,
        "reason": None,
        "transactions": [_txn_to_dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "merchant_id": account.provider_merchant_id or account.provider_account_id,
    }


async def sync_paypal_transactions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    account: TenantPaymentProviderAccount | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> int:
    settings = get_settings()
    if not settings.paypal_transaction_search_enabled:
        raise PaypalTransactionError(
            "PayPal transaction search is not enabled",
            code=REPORTING_ACCESS_REQUIRED,
        )

    account = account or await get_paypal_account_for_tenant(db, tenant_id)
    if account is None or not account.transactions_visibility:
        raise PaypalTransactionError(
            "PayPal transaction visibility is not available",
            code=REPORTING_ACCESS_REQUIRED,
        )

    end = end_date or datetime.now(timezone.utc)
    start = start_date or (end - timedelta(days=30))
    provider_account_id = account.provider_merchant_id or account.provider_account_id

    client = get_paypal_client()
    try:
        payload = await client.request_json(
            "GET",
            "/v1/reporting/transactions",
            params={
                "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fields": "all",
                "page_size": 100,
                "page": 1,
            },
        )
    except PaypalApiError as exc:
        account.last_error_code = exc.error_code
        account.last_error_message = str(exc)[:512]
        await db.flush()
        raise PaypalTransactionError(str(exc), code=exc.error_code) from exc

    upserted = 0
    now = datetime.now(timezone.utc)
    for detail in payload.get("transaction_details") or []:
        if not isinstance(detail, dict):
            continue
        info = detail.get("transaction_info") or {}
        txn_id = str(info.get("transaction_id") or "").strip()
        if not txn_id:
            continue

        existing = (
            await db.execute(
                select(ProviderTransaction).where(
                    ProviderTransaction.tenant_id == tenant_id,
                    ProviderTransaction.provider == PROVIDER_PAYPAL,
                    ProviderTransaction.provider_transaction_id == txn_id,
                )
            )
        ).scalar_one_or_none()

        amount = info.get("transaction_amount") or {}
        fee = info.get("fee_amount") or {}
        payer = (detail.get("payer_info") or {}).get("email_address")
        row = existing or ProviderTransaction(
            tenant_id=tenant_id,
            provider=PROVIDER_PAYPAL,
            provider_account_id=provider_account_id,
            provider_transaction_id=txn_id,
        )
        if existing is None:
            db.add(row)

        row.provider_account_id = provider_account_id
        row.transaction_type = str(info.get("transaction_event_code") or "")[:64] or None
        row.status = str(info.get("transaction_status") or "")[:64] or None
        row.currency = str(amount.get("currency_code") or "")[:3] or None
        row.gross_amount = str(amount.get("value")) if amount.get("value") is not None else None
        row.fee_amount = str(fee.get("value")) if fee.get("value") is not None else None
        if row.gross_amount is not None and row.fee_amount is not None:
            try:
                net = float(row.gross_amount) - float(row.fee_amount)
                row.net_amount = f"{net:.2f}"
            except ValueError:
                row.net_amount = None
        row.recipient = str(payer)[:255] if payer else None
        row.occurred_at = _parse_dt(info.get("transaction_initiation_date"))
        row.raw_payload_hash = _payload_hash(detail)
        row.last_synced_at = now
        upserted += 1

    account.last_transaction_sync_at = now
    account.last_error_code = None
    account.last_error_message = None
    await db.flush()
    return upserted


def _txn_to_dict(row: ProviderTransaction) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "provider_account_id": row.provider_account_id,
        "provider_transaction_id": row.provider_transaction_id,
        "transaction_type": row.transaction_type,
        "status": row.status,
        "currency": row.currency,
        "gross_amount": row.gross_amount,
        "fee_amount": row.fee_amount,
        "net_amount": row.net_amount,
        "recipient": row.recipient,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
    }
