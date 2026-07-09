"""Stripe webhook receiver - no JWT; signature verification only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import get_db
from app.config import get_settings
from app.tenant_rls import apply_platform_lookup_session, clear_platform_lookup_session
from app.services.payments.stripe_global_payouts_service import (
    process_global_payouts_webhook_event,
    verify_global_payouts_webhook,
)
from app.services.payments.stripe_service import (
    StripeServiceError,
    process_stripe_webhook_event,
    record_webhook_event_once,
    verify_stripe_webhook,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["stripe-webhook"])


@router.post("/stripe")
async def stripe_webhook_receive(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    settings = get_settings()
    if not settings.stripe_webhook_secret.strip():
        raise HTTPException(503, "Stripe webhook secret is not configured")

    try:
        payload = await request.body()
    except ClientDisconnect:
        logger.info("stripe_webhook_client_disconnect")
        return {"received": True, "duplicate": False}

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = verify_stripe_webhook(payload, signature)
    except StripeServiceError as exc:
        message = str(exc)
        if "not configured" in message.lower():
            raise HTTPException(503, message) from exc
        raise HTTPException(400, message) from exc

    await apply_platform_lookup_session(db)
    try:
        try:
            result = await record_webhook_event_once(db, event)
        except StripeServiceError as exc:
            raise HTTPException(500, str(exc)) from exc

        if not result.duplicate and not result.already_processed:
            try:
                await process_stripe_webhook_event(db, event, webhook_row=result.event)
            except Exception as exc:
                logger.exception(
                    "stripe_webhook_processing_failed",
                    stripe_event_id=result.event.stripe_event_id,
                    event_type=result.event.event_type,
                    error=str(exc),
                )
                raise HTTPException(500, "Unable to process Stripe webhook event") from exc

        logger.info(
            "stripe_webhook_received",
            stripe_event_id=result.event.stripe_event_id,
            event_type=result.event.event_type,
            duplicate=result.duplicate,
        )
        return {"received": True, "duplicate": result.duplicate}
    finally:
        await clear_platform_lookup_session(db)


@router.post("/stripe/billing")
async def stripe_platform_billing_webhook_receive(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    settings = get_settings()
    if not settings.stripe_platform_billing_webhook_secret.strip():
        raise HTTPException(503, "Platform billing webhook secret is not configured")

    try:
        payload = await request.body()
    except ClientDisconnect:
        logger.info("stripe_platform_billing_webhook_client_disconnect")
        return {"received": True, "duplicate": False}

    signature = request.headers.get("Stripe-Signature", "")
    from app.services.payments.stripe_platform_billing_service import (
        process_platform_billing_webhook_event,
        record_platform_billing_webhook_once,
        verify_platform_billing_webhook,
    )

    try:
        event = verify_platform_billing_webhook(payload, signature)
    except StripeServiceError as exc:
        message = str(exc)
        if "not configured" in message.lower():
            raise HTTPException(503, message) from exc
        raise HTTPException(400, message) from exc

    await apply_platform_lookup_session(db)
    try:
        try:
            result = await record_platform_billing_webhook_once(db, event)
        except StripeServiceError as exc:
            raise HTTPException(500, str(exc)) from exc

        if not result.duplicate and not result.already_processed:
            try:
                await process_platform_billing_webhook_event(
                    db, event, webhook_row=result.event
                )
                await db.commit()
            except Exception as exc:
                logger.exception(
                    "stripe_platform_billing_webhook_processing_failed",
                    stripe_event_id=result.event.stripe_event_id,
                    event_type=result.event.event_type,
                    error=str(exc),
                )
                raise HTTPException(500, "Unable to process platform billing webhook") from exc
        else:
            await db.commit()

        logger.info(
            "stripe_platform_billing_webhook_received",
            stripe_event_id=result.event.stripe_event_id,
            event_type=result.event.event_type,
            duplicate=result.duplicate,
        )
        return {"received": True, "duplicate": result.duplicate}
    finally:
        await clear_platform_lookup_session(db)


@router.post("/stripe/global-payouts")
async def stripe_global_payouts_webhook_receive(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Placeholder receiver for Stripe Global Payouts money management events — no payment mutation yet."""
    try:
        payload = await request.body()
    except ClientDisconnect:
        logger.info("stripe_global_payouts_webhook_client_disconnect")
        return {"received": True}

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = verify_global_payouts_webhook(payload, signature)
    except StripeServiceError as exc:
        raise HTTPException(400, str(exc)) from exc

    event_type = str(event.get("type") or "")
    event_id = str(event.get("id") or "")
    logger.info(
        "stripe_global_payouts_webhook_received",
        stripe_event_id=event_id or None,
        event_type=event_type or None,
    )
    try:
        await process_global_payouts_webhook_event(db, event)
        await db.commit()
    except Exception as exc:
        logger.warning(
            "stripe_global_payouts_webhook_process_failed",
            stripe_event_id=event_id or None,
            event_type=event_type or None,
            error=str(exc),
        )
    return {"received": True}
