"""Viber Public Account Bot API — admin APIs and webhook processing."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import AuthContext, get_db, require_admin
from app.database import db_session_with_rls, platform_lookup_session
from app.models.connected_viber import ConnectedViberAccount
from app.schemas.common import ApiEnvelope
from app.schemas.viber import (
    ViberConnectBody,
    ViberConnectResponse,
    ViberConnectionResponse,
    ViberStatusResponse,
    ViberTestResponse,
)
from app.services.shared.public_api_url import probe_public_webhook, webhook_viber_url
from app.services.ingest.viber_connection_service import (
    connect_viber_bot,
    disconnect_connection,
    find_connection_by_signature,
    list_connections,
    resolve_auth_token,
    test_connection,
)
from app.services.ingest.viber_client import WELCOME_EVENT_TYPES
from app.services.ingest.viber_ingest_service import ingest_viber_message, send_viber_welcome
from app.services.ingest.whatsapp_connection_service import try_claim_message_mid
from app.utils.logger import get_logger
from app.workers.tasks import queue_invoices_for_processing

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/viber", tags=["viber"])
webhook_router = APIRouter(tags=["viber-webhook"])

_VIBER_OK = {"status": 0}


def _to_connection(row: ConnectedViberAccount) -> ViberConnectionResponse:
    return ViberConnectionResponse.model_validate(row)


def viber_configured(connections: list[ConnectedViberAccount]) -> bool:
    return any(row.is_connected for row in connections)


@router.get("/status", response_model=ApiEnvelope[ViberStatusResponse])
async def viber_status(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[ViberStatusResponse]:
    connections = await list_connections(db, tenant_id=ctx.tenant_id)
    callback_url = webhook_viber_url()
    reachable, hint = await probe_public_webhook(callback_url)
    return ApiEnvelope(
        data=ViberStatusResponse(
            configured=viber_configured(connections),
            webhook_callback_url=callback_url,
            webhook_reachable=reachable,
            webhook_reachability_hint=hint,
            connections=[_to_connection(row) for row in connections],
        )
    )


@router.post("/connect", response_model=ApiEnvelope[ViberConnectResponse])
async def viber_connect(
    body: ViberConnectBody,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[ViberConnectResponse]:
    callback_url = webhook_viber_url()
    reachable, hint = await probe_public_webhook(callback_url)
    if not reachable:
        raise HTTPException(
            400,
            hint or "Webhook URL is not reachable. Start ngrok http 8001 and set PUBLIC_TUNNEL_URL.",
        )
    try:
        row = await connect_viber_bot(
            db,
            tenant_id=ctx.tenant_id,
            auth_token=body.auth_token,
        )
        profile_name: str | None = None
        try:
            from app.services.ingest.viber_client import ViberClient

            info = await ViberClient(body.auth_token.strip()).get_account_info()
            profile_name = str(info.get("name") or "") or None
        except Exception:
            pass
        return ApiEnvelope(
            data=ViberConnectResponse(
                connection=_to_connection(row),
                bot_name=profile_name,
            )
        )
    except Exception as exc:
        logger.warning("viber_connect_failed", error=str(exc), tenant_id=ctx.tenant_id)
        raise HTTPException(400, str(exc)) from exc


@router.delete("/disconnect/{connection_id}", response_model=ApiEnvelope[dict])
async def viber_disconnect(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    row = await db.get(ConnectedViberAccount, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Viber connection not found")
    await disconnect_connection(db, row)
    return ApiEnvelope(data={"disconnected": True, "id": connection_id})


@router.post("/test/{connection_id}", response_model=ApiEnvelope[ViberTestResponse])
async def viber_test(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[ViberTestResponse]:
    row = await db.get(ConnectedViberAccount, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Viber connection not found")
    try:
        outcome = await test_connection(db, row)
    except Exception as exc:
        row.integration_health = "error"
        await db.flush()
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(
        data=ViberTestResponse(
            ok=row.integration_health == "connected",
            integration_health=row.integration_health,
            warnings=outcome.get("warnings") or [],
            profile=outcome.get("profile") or {},
        )
    )


@webhook_router.get("/webhook/viber")
async def viber_webhook_health() -> dict[str, int]:
    return _VIBER_OK


async def process_viber_payload(raw_body: bytes, signature: str | None) -> None:
    try:
        async with platform_lookup_session() as lookup:
            connection = await find_connection_by_signature(lookup, raw_body, signature)
        if not connection:
            logger.warning("viber_unknown_connection", has_sig=bool(signature))
            return

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("viber_invalid_json")
            return

        event = str(payload.get("event") or "")
        if event in WELCOME_EVENT_TYPES:
            try:
                token = resolve_auth_token(connection)
            except Exception as exc:
                logger.error(
                    "viber_token_missing",
                    connection_id=connection.id,
                    error=str(exc),
                )
                return
            await send_viber_welcome(auth_token=token, event=payload)
            logger.info(
                "viber_welcome_sent",
                viber_event=event,
                tenant_id=connection.tenant_id,
            )
            return

        if event != "message":
            logger.debug("viber_skip_event", viber_event=event)
            return

        message_token = str(payload.get("message_token") or "")
        if not message_token:
            logger.warning("viber_missing_message_token")
            return

        async with db_session_with_rls(connection.tenant_id) as session:
            if not await try_claim_message_mid(
                session,
                message_token,
                tenant_id=connection.tenant_id,
            ):
                from app.services.ingest.ingest_skip_service import log_ingest_skip

                logger.info("viber_dedupe_skip", message_token=message_token)
                await log_ingest_skip(
                    session,
                    reason="webhook_dedupe_skip",
                    channel="viber",
                    tenant_id=connection.tenant_id,
                    message_id=message_token,
                )
                await session.commit()
                return

            try:
                token = resolve_auth_token(connection)
            except Exception as exc:
                from app.services.ingest.ingest_skip_service import log_ingest_skip

                logger.error(
                    "viber_token_missing",
                    connection_id=connection.id,
                    error=str(exc),
                )
                await log_ingest_skip(
                    session,
                    reason="mailbox_token_failed",
                    channel="viber",
                    tenant_id=connection.tenant_id,
                    message_id=message_token,
                    exc_type=type(exc).__name__,
                )
                await session.commit()
                return

            result = await ingest_viber_message(
                session,
                connection=connection,
                event=payload,
                auth_token=token,
            )
            queued_invoice_ids = list(result.invoice_ids or [])

        if queued_invoice_ids:
            await queue_invoices_for_processing(
                queued_invoice_ids,
                tenant_id=connection.tenant_id,
            )

        logger.info(
            "viber_message_processed",
            message_token=message_token,
            ingested=result.ingested_count,
            skipped=result.skipped_reason,
            tenant_id=connection.tenant_id,
        )
    except Exception as exc:
        logger.exception("viber_webhook_processing_failed", error=str(exc))


def schedule_viber_webhook_processing(raw_body: bytes, signature: str | None) -> None:
    task = asyncio.create_task(process_viber_payload(raw_body, signature))

    def _log_task_result(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("viber_webhook_task_failed", error=str(exc))

    task.add_done_callback(_log_task_result)


@webhook_router.post("/webhook/viber")
async def viber_webhook_receive(request: Request) -> dict[str, int]:
    logger.info("viber_webhook_post_received", path=str(request.url.path))
    try:
        raw = await request.body()
    except ClientDisconnect:
        logger.info("viber_webhook_client_disconnect")
        return _VIBER_OK

    signature = request.headers.get("X-Viber-Content-Signature")
    schedule_viber_webhook_processing(raw, signature)
    return _VIBER_OK
