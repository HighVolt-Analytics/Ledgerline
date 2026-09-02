"""Connected Outlook mailboxes for the organisation."""

import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode
import uuid

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, bind_db_to_tenant, get_auth_context, get_db, require_admin
from app.schemas.rule_book_config import EmailCaptureRule, RuleConditionGroup
from app.services.auth.privilege_service import require_privilege
from app.tenant_scoped import get_for_tenant
from app.config import get_settings
from app.models.connected_mailbox import AUTH_DELEGATED, ConnectedMailbox
from app.models.invoice import Invoice
from app.models.mailbox_connection_request import MailboxConnectionRequest
from app.schemas.common import ApiEnvelope
from app.schemas.mailbox import (
    MailboxAdminConsentResponse,
    MailboxAuthorizeResponse,
    MailboxBackfillCreate,
    MailboxBackfillQueuedResponse,
    MailboxBackfillResponse,
    MailboxConnectionRequestCreate,
    MailboxConnectionRequestActionResponse,
    MailboxConnectionRequestResponse,
    MailboxCreate,
    MailboxInviteLinkResponse,
    MailboxInvitePreviewResponse,
    MailboxResponse,
)
from app.services.ingest.mailbox_backfill_service import (
    create_mailbox_backfill_job,
    get_mailbox_backfill_job,
)
from app.services.ingest.mailbox_invite_service import (
    build_connect_url_for_request,
    build_invite_oauth_url,
    create_mailbox_connection_request,
    get_invite_request,
    load_invite_for_token,
    parse_invite_token,
    resend_mailbox_connection_request,
)
from app.services.ingest.mailbox_provider import (
    PROVIDER_UNKNOWN,
    available_providers_for_email,
    resolve_invite_provider,
)
from app.services.ingest.gmail_oauth_service import (
    complete_oauth_callback as complete_gmail_oauth_callback,
    gmail_oauth_configured,
    parse_oauth_state as parse_gmail_oauth_state,
)
from app.services.ingest.mailbox_oauth_service import (
    build_admin_consent_url,
    complete_oauth_callback,
    disconnect_oauth_mailbox,
    mark_application_mailbox,
    oauth_configured,
    parse_oauth_state,
)
from app.services.shared.public_app_url import build_public_app_path
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

_OAUTH_CALLBACK_ERROR_MESSAGE = "Mailbox connection failed. Try again or contact support."


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _invite_context_from_state(
    state: str | None,
) -> tuple[str | None, int | None, uuid.UUID | None]:
    if not state:
        return None, None, None
    payload = None
    for parser in (parse_oauth_state, parse_gmail_oauth_state):
        try:
            payload = parser(state)
            break
        except Exception:
            continue
    if not payload:
        return None, None, None
    if str(payload.get("flow") or "") != "invite":
        return None, None, None
    invite_request_id = payload.get("invite_request_id")
    tenant_id = parse_tenant_id(payload.get("org_id"))
    return (
        "invite",
        int(invite_request_id) if invite_request_id is not None else None,
        tenant_id,
    )


def _tenant_id_from_oauth_state(state: str) -> uuid.UUID:
    for parser in (parse_oauth_state, parse_gmail_oauth_state):
        try:
            payload = parser(state)
            tenant_id = parse_tenant_id(payload.get("org_id"))
            if tenant_id is not None:
                return tenant_id
        except Exception:
            continue
    raise RuntimeError("Invalid OAuth session")


def _oauth_return_url(
    *,
    flow: str | None,
    invite_request_id: int | None,
    tenant_id: uuid.UUID | None,
    settings,
) -> str:
    if flow == "invite":
        if invite_request_id is not None and tenant_id is not None:
            return build_connect_url_for_request(
                request_id=invite_request_id,
                tenant_id=tenant_id,
            )
        return build_public_app_path("/connect-mailbox").rstrip("/")
    return settings.graph_oauth_frontend_return_url.rstrip("/")


def _user_facing_oauth_error(exc: Exception, *, flow: str | None) -> str:
    if flow == "invite" and isinstance(exc, RuntimeError):
        message = str(exc).strip()
        if message:
            return message[:200]
    return _OAUTH_CALLBACK_ERROR_MESSAGE


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])

# Microsoft redirect — must NOT require JWT (mounted without require_user in main.py).
oauth_public_router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


def _to_response(row: ConnectedMailbox) -> MailboxResponse:
    return MailboxResponse.model_validate(row)


def _to_request_response(row: MailboxConnectionRequest) -> MailboxConnectionRequestResponse:
    return MailboxConnectionRequestResponse.model_validate(row)


def _to_action_response(result) -> MailboxConnectionRequestActionResponse:
    return MailboxConnectionRequestActionResponse(
        **_to_request_response(result.row).model_dump(),
        connect_url=result.connect_url,
        email_sent=result.email_sent,
        email_error=result.email_error,
    )


@router.get("/oauth/authorize", response_model=ApiEnvelope[MailboxAuthorizeResponse])
async def mailbox_oauth_authorize(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[MailboxAuthorizeResponse]:
    """Deprecated — use POST /mailboxes/requests to email an invitation."""
    raise HTTPException(
        422,
        "Send a mailbox connection invitation instead (POST /api/mailboxes/requests). "
        "The mailbox owner completes Microsoft consent from the email link.",
    )


@router.get(
    "/oauth/admin-consent-url",
    response_model=ApiEnvelope[MailboxAdminConsentResponse],
)
async def mailbox_oauth_admin_consent_url(
    _ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MailboxAdminConsentResponse]:
    """Return a Microsoft admin-consent URL for IT (one-time org-wide delegated consent)."""
    if not oauth_configured():
        raise HTTPException(503, "Microsoft OAuth is not configured")
    try:
        url = build_admin_consent_url()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return ApiEnvelope(
        data=MailboxAdminConsentResponse(
            admin_consent_url=url,
            instructions=(
                "Open this link signed in as a Microsoft 365 Global Administrator. "
                "Accept consent for the whole organisation once. After that, invited "
                "users can connect mailboxes without seeing 'Need admin approval'."
            ),
        )
    )


@router.post(
    "/requests",
    response_model=ApiEnvelope[MailboxConnectionRequestActionResponse],
    status_code=201,
)
async def create_mailbox_connection_invite(
    body: MailboxConnectionRequestCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MailboxConnectionRequestActionResponse]:
    if not oauth_configured() and not gmail_oauth_configured():
        raise HTTPException(
            503,
            "Mailbox OAuth is not configured. Set Microsoft (AZURE_*) and/or Google "
            "(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_OAUTH_REDIRECT_URI) credentials.",
        )
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to send invitations")
    from app.services.credit_service import PlanFeatureBlockedError, assert_can_ingest_via_channel

    try:
        await assert_can_ingest_via_channel(db, ctx.tenant_id, channel="email")
    except PlanFeatureBlockedError as exc:
        raise HTTPException(403, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        result = await create_mailbox_connection_request(
            db,
            tenant_id=ctx.tenant_id,
            requested_email=str(body.email),
            display_name=body.display_name,
            message=body.message,
            requested_by_user_id=ctx.user_id,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return ApiEnvelope(data=_to_action_response(result))


@router.get(
    "/requests",
    response_model=ApiEnvelope[list[MailboxConnectionRequestResponse]],
)
async def list_mailbox_connection_requests(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[MailboxConnectionRequestResponse]]:
    rows = (
        await db.execute(
            select(MailboxConnectionRequest)
            .where(MailboxConnectionRequest.tenant_id == ctx.tenant_id)
            .order_by(MailboxConnectionRequest.created_at.desc())
        )
    ).scalars().all()
    return ApiEnvelope(data=[_to_request_response(r) for r in rows])


@router.post(
    "/requests/{request_id}/resend",
    response_model=ApiEnvelope[MailboxConnectionRequestActionResponse],
)
async def resend_mailbox_connection_invite(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MailboxConnectionRequestActionResponse]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to resend invitations")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        result = await resend_mailbox_connection_request(
            db,
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiEnvelope(data=_to_action_response(result))


@router.get(
    "/requests/{request_id}/link",
    response_model=ApiEnvelope[MailboxInviteLinkResponse],
)
async def get_mailbox_connection_invite_link(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[MailboxInviteLinkResponse]:
    try:
        row = await get_invite_request(db, request_id=request_id, tenant_id=ctx.tenant_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    url = build_connect_url_for_request(request_id=row.id, tenant_id=row.tenant_id)
    return ApiEnvelope(data=MailboxInviteLinkResponse(connect_url=url))


@oauth_public_router.get(
    "/invites/preview",
    response_model=ApiEnvelope[MailboxInvitePreviewResponse],
)
async def preview_mailbox_invite(
    token: str = Query(..., min_length=10),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[MailboxInvitePreviewResponse]:
    try:
        invite_ids = parse_invite_token(token)
        tenant_id = invite_ids["org_id"]
        if not isinstance(tenant_id, uuid.UUID):
            tenant_id = uuid.UUID(str(tenant_id))
        await bind_db_to_tenant(db, tenant_id)
        row, org = await load_invite_for_token(db, token)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired invitation") from exc
    return ApiEnvelope(
        data=MailboxInvitePreviewResponse(
            tenant_name=org.name,
            requested_email=row.requested_email,
            display_name=row.display_name,
            message=row.message,
            expires_at=row.expires_at,
            mail_provider=(
                resolved
                if (resolved := resolve_invite_provider(
                    row.requested_email,
                    stored=row.mail_provider,
                ))
                != PROVIDER_UNKNOWN
                else None
            ),
            available_providers=available_providers_for_email(row.requested_email),
            google_oauth_configured=gmail_oauth_configured(),
            microsoft_oauth_configured=oauth_configured(),
        )
    )


@oauth_public_router.get(
    "/invites/authorize",
    response_model=ApiEnvelope[MailboxAuthorizeResponse],
)
async def authorize_mailbox_invite(
    token: str = Query(..., min_length=10),
    provider: str | None = Query(None, description="google or microsoft"),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[MailboxAuthorizeResponse]:
    try:
        invite_ids = parse_invite_token(token)
        tenant_id = invite_ids["org_id"]
        if not isinstance(tenant_id, uuid.UUID):
            tenant_id = uuid.UUID(str(tenant_id))
        await bind_db_to_tenant(db, tenant_id)
        row, _org = await load_invite_for_token(db, token)
        resolved = resolve_invite_provider(
            row.requested_email,
            stored=row.mail_provider,
            requested=provider,
        )
        if resolved != PROVIDER_UNKNOWN and row.mail_provider != resolved:
            row.mail_provider = resolved
            await db.flush()
        url = build_invite_oauth_url(
            tenant_id=row.tenant_id,
            invite_request_id=row.id,
            requested_email=row.requested_email,
            stored_provider=row.mail_provider,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return ApiEnvelope(
        data=MailboxAuthorizeResponse(
            authorize_url=url,
            mail_provider=resolved,
        )
    )


@oauth_public_router.get("/oauth/callback")
async def mailbox_oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """OAuth redirect target — exchanges code and returns user to the frontend."""
    settings = get_settings()
    flow, invite_request_id, tenant_id = _invite_context_from_state(state)
    params: dict[str, str] = {}

    def return_url() -> str:
        return _oauth_return_url(
            flow=flow,
            invite_request_id=invite_request_id,
            tenant_id=tenant_id,
            settings=settings,
        )

    if error:
        params["mailbox_oauth"] = "error"
        params["message"] = (error_description or error)[:200]
        return RedirectResponse(_append_query(return_url(), params))

    if not code or not state:
        params["mailbox_oauth"] = "error"
        params["message"] = "Missing authorization code"
        return RedirectResponse(_append_query(return_url(), params))

    try:
        await bind_db_to_tenant(db, _tenant_id_from_oauth_state(state))
        mailbox, completed_flow = await complete_oauth_callback(
            db, code=code, state=state
        )
        await db.commit()
        params["mailbox_oauth"] = "success"
        params["email"] = mailbox.email
        if completed_flow == "invite":
            flow = "invite"
            _, invite_request_id, tenant_id = _invite_context_from_state(state)
    except Exception as exc:
        await db.rollback()
        logger.exception("mailbox_oauth_callback_failed", error=str(exc))
        params["mailbox_oauth"] = "error"
        params["message"] = _user_facing_oauth_error(exc, flow=flow)

    return RedirectResponse(_append_query(return_url(), params))


@oauth_public_router.get("/gmail/oauth/callback")
async def gmail_mailbox_oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Google OAuth redirect target for Gmail mailbox connection."""
    settings = get_settings()
    flow, invite_request_id, tenant_id = _invite_context_from_state(state)
    params: dict[str, str] = {}

    def return_url() -> str:
        return _oauth_return_url(
            flow=flow,
            invite_request_id=invite_request_id,
            tenant_id=tenant_id,
            settings=settings,
        )

    if error:
        params["mailbox_oauth"] = "error"
        params["message"] = (error_description or error)[:200]
        return RedirectResponse(_append_query(return_url(), params))

    if not code or not state:
        params["mailbox_oauth"] = "error"
        params["message"] = "Missing authorization code"
        return RedirectResponse(_append_query(return_url(), params))

    try:
        await bind_db_to_tenant(db, _tenant_id_from_oauth_state(state))
        mailbox, completed_flow = await complete_gmail_oauth_callback(
            db, code=code, state=state
        )
        await db.commit()
        params["mailbox_oauth"] = "success"
        params["email"] = mailbox.email
        if completed_flow == "invite":
            flow = "invite"
            _, invite_request_id, tenant_id = _invite_context_from_state(state)
    except Exception as exc:
        await db.rollback()
        logger.exception("gmail_mailbox_oauth_callback_failed", error=str(exc))
        params["mailbox_oauth"] = "error"
        params["message"] = _user_facing_oauth_error(exc, flow=flow)

    return RedirectResponse(_append_query(return_url(), params))


@router.get("", response_model=ApiEnvelope[list[MailboxResponse]])
async def list_mailboxes(
    db: AsyncSession = Depends(get_db),
    ctx=Depends(get_auth_context),
) -> ApiEnvelope[list[MailboxResponse]]:
    rows = (
        await db.execute(
            select(ConnectedMailbox)
            .where(ConnectedMailbox.tenant_id == ctx.tenant_id)
            .order_by(ConnectedMailbox.email)
        )
    ).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(Invoice.connected_mailbox_id, func.count(Invoice.id))
                .where(
                    Invoice.tenant_id == ctx.tenant_id,
                    Invoice.connected_mailbox_id.isnot(None),
                )
                .group_by(Invoice.connected_mailbox_id)
            )
        ).all()
    )
    return ApiEnvelope(
        data=[
            _to_response(row).model_copy(
                update={"document_count": int(counts.get(row.id, 0) or 0)}
            )
            for row in rows
        ]
    )


@router.post("", response_model=ApiEnvelope[MailboxResponse], status_code=201)
async def add_mailbox(
    body: MailboxCreate,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> ApiEnvelope[MailboxResponse]:
    """
    Register a service mailbox for application-permission polling (admin only).

    User mailboxes must use GET /mailboxes/oauth/authorize (Microsoft sign-in + consent).
    """
    if oauth_configured():
        raise HTTPException(
            422,
            "Send a mailbox connection invitation (POST /api/mailboxes/requests). "
            "Direct registration is only for legacy application-permission setups.",
        )

    email = body.email.lower().strip()
    existing = (
        await db.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.tenant_id == ctx.tenant_id,
                ConnectedMailbox.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Mailbox '{email}' is already connected")

    row = ConnectedMailbox(
        tenant_id=ctx.tenant_id,
        email=email,
        display_name=body.display_name or email,
        is_active=True,
    )
    mark_application_mailbox(row)
    db.add(row)
    await db.flush()
    return ApiEnvelope(data=_to_response(row))


class EmailIngestionRulesUpdate(BaseModel):
    email_capture_rules: list[EmailCaptureRule]


class EmailIngestionRuleTestRequest(BaseModel):
    mailbox: str = Field(..., min_length=1)
    root: RuleConditionGroup
    lookback_days: int = Field(default=30, ge=1, le=90)
    rule_name: str = Field(default="Preview rule", min_length=1)


@router.get("/ingestion-rules", response_model=ApiEnvelope[dict[str, Any]])
async def get_email_ingestion_rules(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Return email ingestion rules for Upload → Email setup."""
    from app.services.ingest.email_ingestion_rules_service import load_email_ingestion_rules_dict

    return ApiEnvelope(data=await load_email_ingestion_rules_dict(db, ctx.tenant_id))


@router.get("/ingestion-rules/stats", response_model=ApiEnvelope[dict[str, Any]])
async def get_email_ingestion_rule_stats(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Match counts for ingestion rules (derived from audit logs)."""
    from app.services.ingest.email_ingestion_rules_service import load_email_ingestion_stats_dict

    return ApiEnvelope(data=await load_email_ingestion_stats_dict(db, ctx.tenant_id))


@router.put("/ingestion-rules", response_model=ApiEnvelope[dict[str, Any]])
async def put_email_ingestion_rules(
    body: EmailIngestionRulesUpdate,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Persist email ingestion rules from Upload → Email setup."""
    from app.services.ingest.email_capture_rule_validation import (
        validate_email_capture_rules_warnings_by_id,
    )
    from app.services.ingest.email_ingestion_rules_service import (
        save_email_ingestion_rules,
        validation_http_detail,
    )

    require_privilege(ctx, "Edit Policy")
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    try:
        payload, warnings = await save_email_ingestion_rules(
            db,
            ctx.tenant_id,
            body.email_capture_rules,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, validation_http_detail(exc)) from exc

    return ApiEnvelope(
        data={
            "email_capture_rules": [
                rule.model_dump() for rule in payload.email_capture_rules
            ],
            "warnings": warnings,
            "rule_warnings": validate_email_capture_rules_warnings_by_id(
                payload.email_capture_rules
            ),
        }
    )


@router.get("/ingestion-rules/recent-skips", response_model=ApiEnvelope[dict[str, Any]])
async def get_email_ingestion_recent_skips(
    mailbox: str = Query(..., min_length=1, description="Connected mailbox email address"),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Recent email_skipped audit events for one mailbox (ingest troubleshooting)."""
    from app.services.ingest.email_ingestion_rules_service import load_recent_skips_dict

    return ApiEnvelope(data=await load_recent_skips_dict(db, ctx.tenant_id, mailbox))


@router.post("/ingestion-rules/test", response_model=ApiEnvelope[dict[str, Any]])
async def test_email_ingestion_rule(
    body: EmailIngestionRuleTestRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[dict[str, Any]]:
    """Dry-run a draft ingestion rule against recent mailbox messages (no ingest)."""
    from app.services.ingest.email_capture_preview_service import preview_email_capture_rule
    from app.services.ingest.email_capture_rule_validation import validate_rule_specificity
    from app.services.ingest.email_ingestion_rules_service import build_preview_capture_rule

    require_privilege(ctx, "Edit Policy")
    draft = build_preview_capture_rule(
        mailbox=body.mailbox,
        root=body.root,
        rule_name=body.rule_name,
    )
    result = await preview_email_capture_rule(
        db,
        tenant_id=ctx.tenant_id,
        mailbox=body.mailbox,
        root=body.root,
        lookback_days=body.lookback_days,
        rule_name=body.rule_name,
    )
    result["warnings"] = [
        *list(result.get("warnings") or []),
        *validate_rule_specificity(draft),
    ]
    return ApiEnvelope(data=result)


@router.delete("/{mailbox_id}", status_code=204)
async def remove_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> None:
    row = await get_for_tenant(db, ConnectedMailbox, mailbox_id, ctx.tenant_id)
    if not row:
        raise HTTPException(404, "Mailbox not found")
    await db.execute(
        update(Invoice)
        .where(
            Invoice.tenant_id == ctx.tenant_id,
            Invoice.connected_mailbox_id == mailbox_id,
        )
        .values(connected_mailbox_id=None)
    )
    await db.delete(row)
    await db.flush()


def _to_backfill_response(row) -> MailboxBackfillResponse:
    return MailboxBackfillResponse.model_validate(row)


@router.post(
    "/{mailbox_id}/backfill",
    response_model=ApiEnvelope[MailboxBackfillQueuedResponse],
    status_code=202,
)
async def start_mailbox_backfill(
    mailbox_id: int,
    body: MailboxBackfillCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[MailboxBackfillQueuedResponse]:
    """Queue historical import for messages with attachments from a starting date through today."""
    from datetime import date as date_type

    settings = get_settings()
    to_day = body.to_date or date_type.today()
    try:
        job = await create_mailbox_backfill_job(
            db,
            tenant_id=ctx.tenant_id,
            mailbox_id=mailbox_id,
            from_day=body.from_date,
            to_day=to_day,
            mark_processed=body.mark_processed,
            requested_by_user_id=ctx.user_id,
        )
        await db.commit()
        await db.refresh(job)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    task_id = "inline"
    if settings.sync_processing:
        from app.workers.tasks import run_mailbox_backfill_background

        background_tasks.add_task(
            run_mailbox_backfill_background, job.id, tenant_id=ctx.tenant_id
        )
    else:
        try:
            from app.workers.tasks import mailbox_backfill_task

            async_result = mailbox_backfill_task.delay(job.id, tenant_id=ctx.tenant_id)
            task_id = async_result.id
            job.celery_task_id = task_id
            await db.commit()
        except Exception:
            from app.workers.tasks import run_mailbox_backfill_background

            background_tasks.add_task(
                run_mailbox_backfill_background, job.id, tenant_id=ctx.tenant_id
            )

    return ApiEnvelope(
        data=MailboxBackfillQueuedResponse(
            job=_to_backfill_response(job),
            task_id=task_id,
        )
    )


@router.get(
    "/{mailbox_id}/backfill/{job_id}",
    response_model=ApiEnvelope[MailboxBackfillResponse],
)
async def get_mailbox_backfill_status(
    mailbox_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[MailboxBackfillResponse]:
    try:
        job = await get_mailbox_backfill_job(db, job_id=job_id, tenant_id=ctx.tenant_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if job.mailbox_id != mailbox_id:
        raise HTTPException(404, "Import job not found")
    return ApiEnvelope(data=_to_backfill_response(job))


@router.patch("/{mailbox_id}/toggle", response_model=ApiEnvelope[MailboxResponse])
async def toggle_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> ApiEnvelope[MailboxResponse]:
    row = await get_for_tenant(db, ConnectedMailbox, mailbox_id, ctx.tenant_id)
    if not row:
        raise HTTPException(404, "Mailbox not found")
    row.is_active = not row.is_active
    row.last_poll_at = row.last_poll_at or datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(row)
    return ApiEnvelope(data=_to_response(row))


@router.post("/{mailbox_id}/disconnect", response_model=ApiEnvelope[MailboxResponse])
async def disconnect_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> ApiEnvelope[MailboxResponse]:
    """Revoke stored OAuth tokens for a delegated mailbox."""
    row = await get_for_tenant(db, ConnectedMailbox, mailbox_id, ctx.tenant_id)
    if not row:
        raise HTTPException(404, "Mailbox not found")
    if row.auth_type != AUTH_DELEGATED:
        raise HTTPException(422, "Only OAuth-connected mailboxes can be disconnected")
    disconnect_oauth_mailbox(row)
    await db.flush()
    await db.refresh(row)
    return ApiEnvelope(data=_to_response(row))
