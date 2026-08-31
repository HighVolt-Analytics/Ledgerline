"""Xero webhook receiver — HMAC validation, dedupe, enqueue reconcile jobs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bind_db_to_tenant, cross_tenant_db_lookup, get_db
from app.config import get_settings
from app.models.accounting_sync_job import JOB_TYPE_RECONCILE
from app.models.xero_connection import XeroConnection
from app.models.xero_webhook_event import XeroWebhookEvent
from app.integrations.xero.sync_jobs import enqueue_sync_job
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["xero-webhooks"])


def _verify_signature(raw_body: bytes, signature_header: str | None, *, key: str) -> bool:
    if not key or not signature_header:
        return False
    digest = base64.b64encode(
        hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("ascii")
    return hmac.compare_digest(digest, signature_header.strip())


def _event_key(*, xero_tenant_id: str, category: str, event_type: str, resource_id: str) -> str:
    return f"{xero_tenant_id}:{category}:{event_type}:{resource_id}"


async def _resolve_tenant_id(
    db: AsyncSession,
    xero_tenant_id: str,
) -> uuid.UUID | None:
    async with cross_tenant_db_lookup(db):
        row = (
            await db.execute(
                select(XeroConnection.tenant_id)
                .where(
                    XeroConnection.xero_tenant_id == xero_tenant_id,
                    XeroConnection.active.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    return row


@router.post("/xero")
async def xero_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    raw = await request.body()
    signature = request.headers.get("x-xero-signature")
    webhook_key = get_settings().xero_webhook_key.strip()
    if not webhook_key:
        raise HTTPException(503, "Xero webhook key not configured")

    signature_valid = _verify_signature(raw, signature, key=webhook_key)
    if not signature_valid:
        raise HTTPException(401, "Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON payload") from exc

    events = payload.get("events") or []
    payload_text = raw.decode("utf-8") if raw else None
    enqueued_reconcile = 0

    if not events:
        logger.info("xero_webhook_intent_received", signature_valid=signature_valid)
        intent_key = "intent:receive"
        existing_intent = (
            await db.execute(
                select(XeroWebhookEvent).where(XeroWebhookEvent.event_key == intent_key)
            )
        ).scalar_one_or_none()
        if existing_intent is None:
            db.add(
                XeroWebhookEvent(
                    event_key=intent_key,
                    xero_tenant_id=None,
                    tenant_id=None,
                    event_category="intent",
                    event_type="intent_to_receive",
                    payload_json=payload_text,
                    signature_valid=True,
                )
            )
        await db.commit()
        return {"status": "ok"}

    tenants_needing_reconcile: set[uuid.UUID] = set()

    for event in events:
        xero_tenant_id = str(event.get("tenantId") or "")
        category = str(event.get("eventCategory") or "")
        event_type = str(event.get("eventType") or "")
        resource_id = str(event.get("resourceId") or event.get("resourceUrl") or "")
        if not xero_tenant_id:
            continue
        key = _event_key(
            xero_tenant_id=xero_tenant_id,
            category=category,
            event_type=event_type,
            resource_id=resource_id,
        )
        existing = (
            await db.execute(
                select(XeroWebhookEvent).where(XeroWebhookEvent.event_key == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        tenant_id = await _resolve_tenant_id(db, xero_tenant_id)
        db.add(
            XeroWebhookEvent(
                event_key=key,
                xero_tenant_id=xero_tenant_id,
                tenant_id=tenant_id,
                event_category=category or None,
                event_type=event_type or None,
                payload_json=json.dumps(event, default=str),
                signature_valid=True,
            )
        )
        if tenant_id is not None:
            await bind_db_to_tenant(db, tenant_id)
            logger.info(
                "xero_webhook_received",
                xero_tenant_id=xero_tenant_id,
                event_category=category,
                event_type=event_type,
            )
            if category.upper() in {"INVOICE", "CREDITNOTE", "PAYMENT"}:
                tenants_needing_reconcile.add(tenant_id)

    for tenant_id in tenants_needing_reconcile:
        await bind_db_to_tenant(db, tenant_id)
        await enqueue_sync_job(
            db,
            tenant_id=tenant_id,
            job_type=JOB_TYPE_RECONCILE,
            direction="inbound",
            entity_type="invoice",
            trigger_type="webhook",
        )
        enqueued_reconcile += 1
        logger.info(
            "xero_webhook_reconcile_enqueued",
            tenant_id=str(tenant_id),
        )

    await db.commit()
    return {"status": "ok", "reconcile_jobs_enqueued": str(enqueued_reconcile)}
