"""Redis-backed dedup for invoice pipeline Celery enqueues."""

from __future__ import annotations

import ssl
import uuid

import redis

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CLAIM_PREFIX = "ll:pipeline:enqueued"


def _claim_key(tenant_id: uuid.UUID, invoice_id: int) -> str:
    return f"{_CLAIM_PREFIX}:{tenant_id}:{invoice_id}"


def _redis_client() -> redis.Redis | None:
    settings = get_settings()
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    kwargs: dict[str, object] = {"decode_responses": True}
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    try:
        return redis.from_url(url, **kwargs)
    except Exception as exc:
        logger.warning("pipeline_enqueue_redis_unavailable", error=str(exc))
        return None


def try_claim_pipeline_enqueue(tenant_id: uuid.UUID, invoice_id: int) -> bool:
    """Return True when this caller may enqueue; False if already claimed recently."""
    client = _redis_client()
    if client is None:
        return True
    settings = get_settings()
    ttl = max(60, int(settings.stuck_pending_requeue_after_seconds))
    key = _claim_key(tenant_id, invoice_id)
    try:
        claimed = bool(client.set(key, "1", nx=True, ex=ttl))
        if not claimed:
            logger.info(
                "pipeline_enqueue_skipped_duplicate",
                tenant_id=str(tenant_id),
                invoice_id=invoice_id,
            )
        return claimed
    except Exception as exc:
        logger.warning(
            "pipeline_enqueue_claim_failed",
            tenant_id=str(tenant_id),
            invoice_id=invoice_id,
            error=str(exc),
        )
        return True


def release_pipeline_enqueue_claim(tenant_id: uuid.UUID, invoice_id: int) -> None:
    """Drop the enqueue claim after the pipeline finishes or fails to publish."""
    client = _redis_client()
    if client is None:
        return
    key = _claim_key(tenant_id, invoice_id)
    try:
        client.delete(key)
    except Exception as exc:
        logger.warning(
            "pipeline_enqueue_release_failed",
            tenant_id=str(tenant_id),
            invoice_id=invoice_id,
            error=str(exc),
        )


def filter_not_already_queued(
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
) -> list[int]:
    """Drop invoice ids that already have a recent pipeline enqueue claim."""
    if not invoice_ids:
        return []
    client = _redis_client()
    if client is None:
        return invoice_ids
    keys = [_claim_key(tenant_id, invoice_id) for invoice_id in invoice_ids]
    try:
        flags = client.mget(keys)
    except Exception as exc:
        logger.warning(
            "pipeline_enqueue_filter_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
        return invoice_ids
    return [
        invoice_id
        for invoice_id, flag in zip(invoice_ids, flags, strict=True)
        if not flag
    ]
