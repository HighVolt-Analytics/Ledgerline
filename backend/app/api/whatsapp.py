"""WhatsApp Business Cloud API — OAuth, admin APIs, and webhook processing."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import AuthContext, bind_db_to_tenant, get_db, require_admin
from app.config import get_settings
from app.database import db_session_with_rls, platform_lookup_session
from app.models.connected_whatsapp import ConnectedWhatsapp
from app.models.user import User, UserRole
from app.schemas.common import ApiEnvelope
from app.schemas.whatsapp import (
    WhatsappAuthorizeResponse,
    WhatsappConnectionResponse,
    WhatsappStatusResponse,
    WhatsappTestResponse,
)
from app.services.public_api_url import webhook_meta_url, whatsapp_oauth_callback_url
from app.services.whatsapp_connection_service import (
    complete_oauth_and_store_connections,
    create_oauth_state,
    disconnect_connection,
    find_connection_by_phone_or_waba,
    list_connections,
    oauth_configured,
    parse_oauth_state,
    resubscribe_connection_webhooks,
    test_connection,
    try_claim_message_mid,
)
from app.services.whatsapp_graph_client import (
    parse_whatsapp_messages,
    verify_webhook_signature,
)
from app.services.whatsapp_ingest_service import ingest_whatsapp_message
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger
from app.workers.tasks import process_invoice_background

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/whatsapp", tags=["whatsapp"])
public_router = APIRouter(tags=["whatsapp-public"])
webhook_router = APIRouter(tags=["meta-webhook"])

_OAUTH_ERRORS = {
    "no_waba": "No WhatsApp Business Account found. Complete Meta Business setup first.",
    "no_phone": "No phone numbers found on your WhatsApp Business Account.",
    "invalid_state": "OAuth session expired. Try connecting again.",
    "not_admin": "Only admins can connect WhatsApp.",
    "not_configured": "WhatsApp / Meta app credentials are not configured on the server.",
}


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _to_connection(row: ConnectedWhatsapp) -> WhatsappConnectionResponse:
    return WhatsappConnectionResponse.model_validate(row)


@router.get("/status", response_model=ApiEnvelope[WhatsappStatusResponse])
async def whatsapp_status(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[WhatsappStatusResponse]:
    connections = await list_connections(db, tenant_id=ctx.tenant_id)
    for conn in connections:
        if conn.is_connected and conn.whatsapp_business_account_id:
            try:
                await resubscribe_connection_webhooks(conn)
            except Exception as exc:
                logger.debug("whatsapp_resubscribe_skipped", id=conn.id, error=str(exc))
    return ApiEnvelope(
        data=WhatsappStatusResponse(
            configured=oauth_configured(),
            webhook_callback_url=webhook_meta_url(),
            oauth_callback_url=whatsapp_oauth_callback_url(),
            connections=[_to_connection(row) for row in connections],
        )
    )


@router.get("/authorize-url", response_model=ApiEnvelope[WhatsappAuthorizeResponse])
async def whatsapp_authorize_url(
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[WhatsappAuthorizeResponse]:
    if not oauth_configured():
        raise HTTPException(503, _OAUTH_ERRORS["not_configured"])
    from app.services.whatsapp_graph_client import build_oauth_authorize_url

    state = create_oauth_state(tenant_id=ctx.tenant_id, user_id=ctx.user_id or 0)
    return ApiEnvelope(
        data=WhatsappAuthorizeResponse(
            authorize_url=build_oauth_authorize_url(state=state),
        )
    )


@router.delete("/disconnect/{connection_id}", response_model=ApiEnvelope[dict])
async def whatsapp_disconnect(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    row = await db.get(ConnectedWhatsapp, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "WhatsApp connection not found")
    await disconnect_connection(db, row)
    return ApiEnvelope(data={"disconnected": True, "id": connection_id})


@router.post("/test/{connection_id}", response_model=ApiEnvelope[WhatsappTestResponse])
async def whatsapp_test(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[WhatsappTestResponse]:
    row = await db.get(ConnectedWhatsapp, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "WhatsApp connection not found")
    try:
        outcome = await test_connection(db, row)
    except Exception as exc:
        row.integration_health = "error"
        row.last_error = str(exc)[:512]
        await db.flush()
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(
        data=WhatsappTestResponse(
            ok=row.integration_health == "connected",
            integration_health=row.integration_health,
            warnings=outcome.get("warnings") or [],
            profile=outcome.get("profile") or {},
        )
    )


@public_router.get("/auth/whatsapp/callback")
async def whatsapp_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    return_base = settings.whatsapp_frontend_return_url

    if error:
        message = error_description or error
        url = _append_query(return_base, {"wa": "error", "reason": message[:120]})
        return RedirectResponse(url=url, status_code=302)

    if not code or not state:
        url = _append_query(return_base, {"wa": "error", "reason": "missing_code"})
        return RedirectResponse(url=url, status_code=302)

    try:
        payload = parse_oauth_state(state)
        tenant_id = parse_tenant_id(payload["org_id"])
        if tenant_id is None:
            raise ValueError("Invalid OAuth session")
        user_id = int(payload["sub"])
    except Exception as exc:
        logger.warning("whatsapp_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {"wa": "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    await bind_db_to_tenant(db, tenant_id)

    user = await db.get(User, user_id)
    if not user or not user.is_active or user.tenant_id != tenant_id:
        url = _append_query(return_base, {"wa": "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)
    if user.role != UserRole.ADMIN:
        url = _append_query(return_base, {"wa": "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)

    try:
        stored = await complete_oauth_and_store_connections(
            db,
            code=code,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db.commit()
        phone = stored[0].phone_number or stored[0].display_name or "WhatsApp"
        logger.info("whatsapp_oauth_callback_success", tenant_id=tenant_id, phone=phone)
        url = _append_query(
            return_base,
            {"wa": "connected", "phone": phone[:80]},
        )
        return RedirectResponse(url=url, status_code=302)
    except RuntimeError as exc:
        reason = str(exc)
        mapped = reason if reason in _OAUTH_ERRORS else "oauth_failed"
        logger.warning("whatsapp_oauth_callback_runtime_error", reason=reason, tenant_id=tenant_id)
        await db.rollback()
        url = _append_query(return_base, {"wa": "error", "reason": mapped})
        return RedirectResponse(url=url, status_code=302)
    except Exception as exc:
        logger.error("whatsapp_oauth_callback_failed", error=str(exc), tenant_id=tenant_id)
        await db.rollback()
        url = _append_query(return_base, {"wa": "error", "reason": "oauth_failed"})
        return RedirectResponse(url=url, status_code=302)


async def process_whatsapp_payload(payload: dict) -> None:
    try:
        messages = parse_whatsapp_messages(payload)
        if not messages:
            return

        for msg in messages:
            if not msg.message_id:
                continue

            async with platform_lookup_session() as lookup:
                connection = await find_connection_by_phone_or_waba(
                    lookup,
                    phone_number_id=msg.phone_number_id or None,
                    waba_id=msg.waba_id or None,
                )
            if not connection:
                logger.warning(
                    "whatsapp_unknown_connection",
                    phone_number_id=msg.phone_number_id,
                    waba_id=msg.waba_id,
                )
                continue

            async with db_session_with_rls(connection.tenant_id) as session:
                if not await try_claim_message_mid(
                    session,
                    msg.message_id,
                    tenant_id=connection.tenant_id,
                ):
                    logger.info("whatsapp_dedupe_skip", message_id=msg.message_id)
                    continue

                from app.services.whatsapp_connection_service import resolve_access_token

                try:
                    token = resolve_access_token(connection)
                except Exception as exc:
                    logger.error(
                        "whatsapp_token_missing",
                        connection_id=connection.id,
                        error=str(exc),
                    )
                    continue

                result = await ingest_whatsapp_message(
                    session,
                    connection=connection,
                    msg=msg,
                    access_token=token,
                )
                queued_invoice_ids = list(result.invoice_ids or [])

            for invoice_id in queued_invoice_ids:
                asyncio.create_task(
                    process_invoice_background(
                        invoice_id,
                        tenant_id=connection.tenant_id,
                    )
                )

            logger.info(
                "whatsapp_message_processed",
                message_id=msg.message_id,
                ingested=result.ingested_count,
                skipped=result.skipped_reason,
                tenant_id=connection.tenant_id,
            )
    except Exception as exc:
        logger.exception("whatsapp_webhook_processing_failed", error=str(exc))


def schedule_whatsapp_webhook_processing(payload: dict) -> None:
    task = asyncio.create_task(process_whatsapp_payload(payload))

    def _log_task_result(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("whatsapp_webhook_task_failed", error=str(exc))

    task.add_done_callback(_log_task_result)


@webhook_router.get("/webhook/meta")
async def meta_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_effective_verify_token:
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    raise HTTPException(403, "Verification failed")


@webhook_router.post("/webhook/meta")
async def meta_webhook_receive(request: Request) -> dict[str, bool]:
    logger.info("meta_webhook_post_received", path=str(request.url.path))
    try:
        raw = await request.body()
    except ClientDisconnect:
        logger.info("meta_webhook_client_disconnect")
        return {"success": True}

    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(raw, signature):
        raise HTTPException(403, "Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload") from None

    obj = payload.get("object")
    logger.info(
        "meta_webhook_payload",
        object=obj,
        bytes=len(raw),
        has_sig=bool(signature),
    )

    if obj == "whatsapp_business_account":
        schedule_whatsapp_webhook_processing(payload)

    return {"success": True}


@webhook_router.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    return await meta_webhook_verify(hub_mode, hub_verify_token, hub_challenge)


@webhook_router.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request) -> dict[str, bool]:
    return await meta_webhook_receive(request)
