"""PayPal webhook receiver — no JWT; official verify-webhook-signature only."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import get_db
from app.config import get_settings
from app.services.payments.paypal_webhook_service import handle_paypal_webhook
from app.tenant_rls import apply_platform_lookup_session, clear_platform_lookup_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["paypal-webhook"])


@router.post("/paypal")
async def paypal_webhook_receive(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool | str]:
    settings = get_settings()
    if not settings.paypal_webhook_id.strip():
        raise HTTPException(503, "PayPal webhook id is not configured")
    if not settings.paypal_configured:
        raise HTTPException(503, "PayPal is not configured")

    try:
        payload = await request.body()
    except ClientDisconnect:
        logger.info("paypal_webhook_client_disconnect")
        return {"received": True, "duplicate": False}

    headers = {k: v for k, v in request.headers.items()}
    await apply_platform_lookup_session(db)
    try:
        try:
            result = await handle_paypal_webhook(db, headers=headers, body=payload)
        except ValueError as exc:
            message = str(exc)
            if "signature" in message.lower() or "verification" in message.lower():
                raise HTTPException(401, message) from exc
            raise HTTPException(400, message) from exc
        except Exception as exc:
            logger.exception("paypal_webhook_processing_failed", error=str(exc))
            raise HTTPException(500, "Unable to process PayPal webhook event") from exc

        await db.commit()
        return {
            "received": True,
            "duplicate": bool(result.get("duplicate")),
            "status": str(result.get("status") or "ok"),
        }
    finally:
        await clear_platform_lookup_session(db)
