"""Provider-neutral payment provider interface (Stripe Connect + PayPal)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_payment_provider import PROVIDER_PAYPAL, PROVIDER_STRIPE
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PaymentProviderError(Exception):
    """Provider selection or capability error."""


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    async def connect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def disconnect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def readiness(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]: ...

    async def get_balance(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]: ...

    async def list_transactions(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def create_payment(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payment_id: int,
        **kwargs: Any,
    ) -> Any: ...

    async def get_payment_status(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        attempt_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes | str,
        **kwargs: Any,
    ) -> Any: ...


class StripePaymentProvider:
    """Thin adapter over existing stripe_service — does not rewrite Stripe internals."""

    name = PROVIDER_STRIPE

    async def connect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.stripe_service import (
            create_connected_account_for_tenant,
            create_account_onboarding_link,
        )

        tenant_name = kwargs.get("tenant_name")
        account = await create_connected_account_for_tenant(
            db, tenant_id, tenant_name=tenant_name
        )
        link = await create_account_onboarding_link(account.stripe_account_id)
        return {
            "provider": self.name,
            "account_id": account.stripe_account_id,
            "onboarding_url": link,
            "onboarding_status": account.onboarding_status,
        }

    async def disconnect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.stripe_service import disconnect_stripe_account_for_tenant

        row = await disconnect_stripe_account_for_tenant(db, tenant_id)
        return {
            "provider": self.name,
            "account_id": row.stripe_account_id,
            "onboarding_status": row.onboarding_status,
        }

    async def readiness(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        from dataclasses import asdict

        from app.services.payments.stripe_service import get_stripe_readiness_for_tenant

        readiness = await get_stripe_readiness_for_tenant(db, tenant_id)
        return asdict(readiness)

    async def get_balance(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        from app.services.payments.stripe_service import (
            get_connected_account_balance,
            get_stripe_account_for_tenant,
        )

        account = await get_stripe_account_for_tenant(db, tenant_id)
        if account is None:
            return {"available": False, "reason": "stripe_not_connected", "balances": []}
        summary = await get_connected_account_balance(
            db, tenant_id, account.stripe_account_id
        )
        return {
            "available": True,
            "reason": None,
            "balances": {
                "available": summary.available,
                "pending": summary.pending,
            },
            "livemode": summary.livemode,
            "snapshot_id": summary.snapshot_id,
        }

    async def list_transactions(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from dataclasses import asdict

        from app.services.payments.stripe_service import (
            get_stripe_account_for_tenant,
            list_connected_account_transactions,
        )

        account = await get_stripe_account_for_tenant(db, tenant_id)
        if account is None:
            return {"available": False, "reason": "stripe_not_connected", "transactions": []}
        limit = int(kwargs.get("limit") or 25)
        rows = await list_connected_account_transactions(
            db, tenant_id, account.stripe_account_id, limit=limit
        )
        return {
            "available": True,
            "reason": None,
            "transactions": [asdict(row) for row in rows],
        }

    async def create_payment(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payment_id: int,
        **kwargs: Any,
    ) -> Any:
        raise PaymentProviderError(
            "Stripe payment execution remains on existing payment execution routes; "
            "use those endpoints explicitly (no provider auto-fallback)."
        )

    async def get_payment_status(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        attempt_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.models.stripe_payments import PaymentAttempt

        attempt = await db.get(PaymentAttempt, attempt_id)
        if attempt is None or (
            attempt.tenant_id is not None and attempt.tenant_id != tenant_id
        ):
            raise PaymentProviderError("Payment attempt not found")
        return {
            "attempt_id": attempt.id,
            "payment_id": attempt.payment_id,
            "provider": attempt.provider or self.name,
            "status": attempt.status,
            "stripe_payment_intent_id": attempt.stripe_payment_intent_id,
            "stripe_transfer_id": attempt.stripe_transfer_id,
            "stripe_payout_id": attempt.stripe_payout_id,
        }

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes | str,
        **kwargs: Any,
    ) -> Any:
        from app.services.payments.stripe_service import verify_stripe_webhook

        signature = ""
        for key, value in headers.items():
            if key.lower() == "stripe-signature":
                signature = value
                break
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        return verify_stripe_webhook(payload, signature)


class PayPalPaymentProvider:
    """Delegates to paypal_* services."""

    name = PROVIDER_PAYPAL

    async def connect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_account_service import connect_paypal_account

        return await connect_paypal_account(db, tenant_id=tenant_id, user_id=user_id)

    async def disconnect(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_account_service import disconnect_paypal_account

        return await disconnect_paypal_account(
            db, tenant_id=tenant_id, user_id=user_id
        )

    async def readiness(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_account_service import get_paypal_readiness

        return await get_paypal_readiness(db, tenant_id)

    async def get_balance(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_balance_service import get_paypal_balance

        return await get_paypal_balance(db, tenant_id)

    async def list_transactions(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_transaction_service import list_paypal_transactions

        return await list_paypal_transactions(
            db,
            tenant_id,
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            page=int(kwargs.get("page") or 1),
            page_size=int(kwargs.get("page_size") or 50),
            sync=bool(kwargs.get("sync", True)),
        )

    async def create_payment(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        payment_id: int,
        **kwargs: Any,
    ) -> Any:
        from app.services.payments.paypal_payout_service import create_paypal_payout

        recipient_method_id = kwargs.get("recipient_method_id")
        if recipient_method_id is None:
            raise PaymentProviderError("recipient_method_id is required")
        amount = kwargs.get("amount")
        if amount is not None and not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        return await create_paypal_payout(
            db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            recipient_method_id=int(recipient_method_id),
            amount=amount,
            currency=kwargs.get("currency"),
            note=kwargs.get("note"),
            actor_user_id=kwargs.get("actor_user_id"),
        )

    async def get_payment_status(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        attempt_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.payments.paypal_payout_service import get_payout_status

        return await get_payout_status(
            db, tenant_id=tenant_id, attempt_id=attempt_id
        )

    async def verify_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes | str,
        **kwargs: Any,
    ) -> Any:
        from app.services.payments.paypal_webhook_service import verify_paypal_webhook

        return await verify_paypal_webhook(headers=headers, body=body)


_PROVIDERS: dict[str, PaymentProvider] = {
    PROVIDER_STRIPE: StripePaymentProvider(),
    PROVIDER_PAYPAL: PayPalPaymentProvider(),
    "paypal": PayPalPaymentProvider(),
    "stripe": StripePaymentProvider(),
}


def get_payment_provider(name: str) -> PaymentProvider:
    """Return the explicitly selected provider. No automatic fallback."""
    key = (name or "").strip().lower()
    provider = _PROVIDERS.get(key)
    if provider is None:
        raise PaymentProviderError(
            f"Unknown payment provider '{name}'. Select 'stripe' or 'paypal' explicitly."
        )
    return provider
