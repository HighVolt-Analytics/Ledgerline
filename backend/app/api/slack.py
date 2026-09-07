"""Slack — OAuth, admin APIs, and Events API webhook processing."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import AuthContext, bind_db_to_tenant, get_db, require_admin
from app.config import get_settings
from app.database import db_session_with_rls, platform_lookup_session
from app.models.connected_slack import ConnectedSlackAccount
from app.models.user import User, UserRole
from app.schemas.common import ApiEnvelope
from app.schemas.slack import (
    SlackAuthorizeResponse,
    SlackConnectionResponse,
    SlackStatusResponse,
    SlackTestResponse,
)
from app.services.shared.public_api_url import slack_oauth_callback_url, webhook_slack_url
from app.services.ingest.slack_connection_service import (
    complete_oauth_and_store_connection,
    create_oauth_state,
    disconnect_connection,
    find_connection_by_team_id,
    list_connections,
    mark_connection_revoked,
    oauth_configured,
    parse_oauth_state,
    resolve_access_token,
    test_connection,
    try_claim_event_id,
)
from app.services.ingest.slack_ingest_service import ingest_slack_message
from app.services.ingest.slack_web_client import parse_slack_payload, verify_slack_signature
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger
from app.workers.tasks import queue_invoices_for_processing

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations/slack", tags=["slack"])
public_router = APIRouter(tags=["slack-public"])
webhook_router = APIRouter(tags=["slack-webhook"])

_OAUTH_ERRORS = {
    "invalid_state": "OAuth session expired. Try connecting again.",
    "not_admin": "Only admins can connect Slack.",
    "not_configured": "Slack app credentials are not configured on the server.",
}


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _to_connection(row: ConnectedSlackAccount) -> SlackConnectionResponse:
    return SlackConnectionResponse.model_validate(row)


@router.get("/status", response_model=ApiEnvelope[SlackStatusResponse])
async def slack_status(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[SlackStatusResponse]:
    connections = await list_connections(db, tenant_id=ctx.tenant_id)
    return ApiEnvelope(
        data=SlackStatusResponse(
            configured=oauth_configured(),
            webhook_callback_url=webhook_slack_url(),
            oauth_callback_url=slack_oauth_callback_url(),
            connections=[_to_connection(row) for row in connections],
        )
    )


@router.get("/authorize-url", response_model=ApiEnvelope[SlackAuthorizeResponse])
async def slack_authorize_url(
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[SlackAuthorizeResponse]:
    if not oauth_configured():
        raise HTTPException(503, _OAUTH_ERRORS["not_configured"])
    from app.services.ingest.slack_web_client import build_oauth_authorize_url

    state = create_oauth_state(tenant_id=ctx.tenant_id, user_id=ctx.user_id or 0)
    return ApiEnvelope(
        data=SlackAuthorizeResponse(
            authorize_url=build_oauth_authorize_url(state=state),
        )
    )


@router.delete("/disconnect/{connection_id}", response_model=ApiEnvelope[dict])
async def slack_disconnect(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    row = await db.get(ConnectedSlackAccount, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Slack connection not found")
    await disconnect_connection(db, row)
    return ApiEnvelope(data={"disconnected": True, "id": connection_id})


@router.post("/test/{connection_id}", response_model=ApiEnvelope[SlackTestResponse])
async def slack_test(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[SlackTestResponse]:
    row = await db.get(ConnectedSlackAccount, connection_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Slack connection not found")
    try:
        outcome = await test_connection(db, row)
    except Exception as exc:
        row.integration_health = "error"
        row.last_error = str(exc)[:512]
        await db.flush()
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(
        data=SlackTestResponse(
            ok=row.integration_health == "connected",
            integration_health=row.integration_health,
            warnings=outcome.get("warnings") or [],
            profile=outcome.get("profile") or {},
        )
    )


@public_router.get("/auth/slack/callback")
async def slack_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    return_base = settings.slack_frontend_return_url

    if error:
        message = error_description or error
        url = _append_query(return_base, {"slack": "error", "reason": message[:120]})
        return RedirectResponse(url=url, status_code=302)

    if not code or not state:
        url = _append_query(return_base, {"slack": "error", "reason": "missing_code"})
        return RedirectResponse(url=url, status_code=302)

    try:
        payload = parse_oauth_state(state)
        tenant_id = parse_tenant_id(payload["org_id"])
        if tenant_id is None:
            raise ValueError("Invalid OAuth session")
        user_id = int(payload["sub"])
    except Exception as exc:
        logger.warning("slack_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {"slack": "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    await bind_db_to_tenant(db, tenant_id)

    user = await db.get(User, user_id)
    if not user or not user.is_active or user.tenant_id != tenant_id:
        url = _append_query(return_base, {"slack": "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)
    if user.role != UserRole.ADMIN:
        url = _append_query(return_base, {"slack": "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)

    try:
        stored = await complete_oauth_and_store_connection(
            db,
            code=code,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db.commit()
        team = stored.team_name or stored.team_id or "Slack"
        logger.info("slack_oauth_callback_success", tenant_id=str(tenant_id), team=team)
        url = _append_query(
            return_base,
            {"slack": "connected", "team": team[:80]},
        )
        return RedirectResponse(url=url, status_code=302)
    except RuntimeError as exc:
        reason = str(exc)
        mapped = reason if reason in _OAUTH_ERRORS else "oauth_failed"
        logger.warning(
            "slack_oauth_callback_runtime_error",
            reason=reason,
            tenant_id=str(tenant_id),
        )
        await db.rollback()
        url = _append_query(return_base, {"slack": "error", "reason": mapped})
        return RedirectResponse(url=url, status_code=302)
    except Exception as exc:
        logger.error(
            "slack_oauth_callback_failed",
            error=str(exc),
            tenant_id=str(tenant_id),
        )
        await db.rollback()
        url = _append_query(return_base, {"slack": "error", "reason": "oauth_failed"})
        return RedirectResponse(url=url, status_code=302)


async def process_slack_payload(payload: dict) -> None:
    try:
        messages, lifecycle = parse_slack_payload(payload)

        for life in lifecycle:
            async with platform_lookup_session() as lookup:
                connection = await find_connection_by_team_id(
                    lookup,
                    team_id=life.team_id,
                    connected_only=False,
                )
            if not connection:
                logger.warning(
                    "slack_lifecycle_unknown_team",
                    team_id=life.team_id,
                    event_type=life.event_type,
                )
                continue

            async with db_session_with_rls(connection.tenant_id) as session:
                # Same dedupe path as message events so Slack retries don't
                # double-fire uninstall/revoke cleanup.
                if not await try_claim_event_id(
                    session,
                    life.event_id,
                    tenant_id=connection.tenant_id,
                ):
                    logger.info(
                        "slack_lifecycle_dedupe_skip",
                        event_id=life.event_id,
                        event_type=life.event_type,
                    )
                    continue
                # Re-load in tenant session
                row = await session.get(ConnectedSlackAccount, connection.id)
                if row is None:
                    continue
                await mark_connection_revoked(
                    session,
                    row,
                    event_type=life.event_type,
                )
            logger.info(
                "slack_connection_revoked",
                team_id=life.team_id,
                event_type=life.event_type,
                tenant_id=str(connection.tenant_id),
            )

        for msg in messages:
            if not msg.event_id:
                continue

            async with platform_lookup_session() as lookup:
                connection = await find_connection_by_team_id(
                    lookup,
                    team_id=msg.team_id,
                    connected_only=True,
                )
            if not connection:
                logger.warning("slack_unknown_connection", team_id=msg.team_id)
                continue

            async with db_session_with_rls(connection.tenant_id) as session:
                if not await try_claim_event_id(
                    session,
                    msg.event_id,
                    tenant_id=connection.tenant_id,
                ):
                    logger.info("slack_dedupe_skip", event_id=msg.event_id)
                    from app.services.ingest.ingest_skip_service import log_ingest_skip

                    await log_ingest_skip(
                        session,
                        reason="webhook_dedupe_skip",
                        channel="slack",
                        tenant_id=connection.tenant_id,
                        message_id=msg.event_id,
                    )
                    continue

                try:
                    token = resolve_access_token(connection)
                except Exception as exc:
                    logger.error(
                        "slack_token_missing",
                        connection_id=connection.id,
                        error=str(exc),
                    )
                    from app.services.ingest.ingest_skip_service import log_ingest_skip

                    await log_ingest_skip(
                        session,
                        reason="token_missing",
                        channel="slack",
                        tenant_id=connection.tenant_id,
                        message_id=msg.event_id,
                        exc_type=type(exc).__name__,
                    )
                    continue

                result = await ingest_slack_message(
                    session,
                    connection=connection,
                    msg=msg,
                    access_token=token,
                )
                queued_invoice_ids = list(result.invoice_ids or [])

            if queued_invoice_ids:
                await queue_invoices_for_processing(
                    queued_invoice_ids,
                    tenant_id=connection.tenant_id,
                )

            logger.info(
                "slack_message_processed",
                event_id=msg.event_id,
                ingested=result.ingested_count,
                skipped=result.skipped_reason,
                tenant_id=str(connection.tenant_id),
            )
    except Exception as exc:
        logger.exception("slack_webhook_processing_failed", error=str(exc))


def schedule_slack_webhook_processing(payload: dict) -> None:
    task = asyncio.create_task(process_slack_payload(payload))

    def _log_task_result(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("slack_webhook_task_failed", error=str(exc))

    task.add_done_callback(_log_task_result)


@webhook_router.post("/webhook/slack/events")
@webhook_router.post("/webhook/slack")
async def slack_webhook_receive(request: Request) -> dict:
    logger.info("slack_webhook_post_received", path=str(request.url.path))
    try:
        raw = await request.body()
    except ClientDisconnect:
        logger.info("slack_webhook_client_disconnect")
        return {"ok": True}

    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")
    if not verify_slack_signature(raw, timestamp, signature):
        raise HTTPException(403, "Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload") from None

    # URL verification challenge (first-time Event Subscriptions setup)
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        return {"challenge": challenge}

    if payload.get("type") == "event_callback":
        schedule_slack_webhook_processing(payload)

    return {"ok": True}


@webhook_router.get("/webhook/slack/events")
@webhook_router.get("/webhook/slack")
async def slack_webhook_get() -> dict[str, bool]:
    """Health / reachability probe for the Slack events URL."""
    return {"ok": True}
