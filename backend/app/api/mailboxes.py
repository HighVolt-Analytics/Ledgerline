"""Connected Outlook mailboxes for the organisation."""

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
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
from app.services.mailbox_backfill_service import (
    create_mailbox_backfill_job,
    get_mailbox_backfill_job,
)
from app.services.mailbox_invite_service import (
    build_connect_url_for_request,
    create_mailbox_connection_request,
    get_invite_request,
    load_invite_for_token,
    resend_mailbox_connection_request,
)
from app.services.mailbox_oauth_service import (
    build_admin_consent_url,
    build_invite_authorize_url,
    complete_oauth_callback,
    disconnect_oauth_mailbox,
    mark_application_mailbox,
    oauth_configured,
    parse_oauth_state,
)
from app.services.public_app_url import build_public_app_path
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
) -> tuple[str | None, int | None, int | None]:
    if not state:
        return None, None, None
    try:
        payload = parse_oauth_state(state)
    except Exception:
        return None, None, None
    if str(payload.get("flow") or "") != "invite":
        return None, None, None
    invite_request_id = payload.get("invite_request_id")
    org_id = payload.get("org_id")
    return (
        "invite",
        int(invite_request_id) if invite_request_id is not None else None,
        int(org_id) if org_id is not None else None,
    )


def _oauth_return_url(
    *,
    flow: str | None,
    invite_request_id: int | None,
    org_id: int | None,
    settings,
) -> str:
    if flow == "invite":
        if invite_request_id is not None and org_id is not None:
            return build_connect_url_for_request(
                request_id=invite_request_id,
                org_id=org_id,
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
    if not oauth_configured():
        raise HTTPException(
            503,
            "Microsoft OAuth is not configured. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "AZURE_CLIENT_SECRET, and GRAPH_OAUTH_REDIRECT_URI.",
        )
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to send invitations")
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        result = await create_mailbox_connection_request(
            db,
            org_id=ctx.org_id,
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
            .where(MailboxConnectionRequest.org_id == ctx.org_id)
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
            org_id=ctx.org_id,
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
        row = await get_invite_request(db, request_id=request_id, org_id=ctx.org_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    url = build_connect_url_for_request(request_id=row.id, org_id=row.org_id)
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
        row, org = await load_invite_for_token(db, token)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired invitation") from exc
    return ApiEnvelope(
        data=MailboxInvitePreviewResponse(
            org_name=org.name,
            requested_email=row.requested_email,
            display_name=row.display_name,
            message=row.message,
            expires_at=row.expires_at,
        )
    )


@oauth_public_router.get(
    "/invites/authorize",
    response_model=ApiEnvelope[MailboxAuthorizeResponse],
)
async def authorize_mailbox_invite(
    token: str = Query(..., min_length=10),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[MailboxAuthorizeResponse]:
    if not oauth_configured():
        raise HTTPException(503, "Microsoft OAuth is not configured")
    try:
        row, _org = await load_invite_for_token(db, token)
        url = build_invite_authorize_url(org_id=row.org_id, invite_request_id=row.id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return ApiEnvelope(data=MailboxAuthorizeResponse(authorize_url=url))


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
    flow, invite_request_id, org_id = _invite_context_from_state(state)
    params: dict[str, str] = {}

    def return_url() -> str:
        return _oauth_return_url(
            flow=flow,
            invite_request_id=invite_request_id,
            org_id=org_id,
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
        mailbox, completed_flow = await complete_oauth_callback(
            db, code=code, state=state
        )
        await db.commit()
        params["mailbox_oauth"] = "success"
        params["email"] = mailbox.email
        if completed_flow == "invite":
            flow = "invite"
            _, invite_request_id, org_id = _invite_context_from_state(state)
    except Exception as exc:
        await db.rollback()
        logger.exception("mailbox_oauth_callback_failed", error=str(exc))
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
            .where(ConnectedMailbox.org_id == ctx.org_id)
            .order_by(ConnectedMailbox.email)
        )
    ).scalars().all()
    return ApiEnvelope(data=[_to_response(r) for r in rows])


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
                ConnectedMailbox.org_id == ctx.org_id,
                ConnectedMailbox.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Mailbox '{email}' is already connected")

    row = ConnectedMailbox(
        org_id=ctx.org_id,
        email=email,
        display_name=body.display_name or email,
        is_active=True,
    )
    mark_application_mailbox(row)
    db.add(row)
    await db.flush()
    return ApiEnvelope(data=_to_response(row))


@router.delete("/{mailbox_id}", status_code=204)
async def remove_mailbox(
    mailbox_id: int,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_admin),
) -> None:
    row = await db.get(ConnectedMailbox, mailbox_id)
    if not row or row.org_id != ctx.org_id:
        raise HTTPException(404, "Mailbox not found")
    await db.execute(
        update(Invoice)
        .where(
            Invoice.org_id == ctx.org_id,
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
    """Queue historical import for messages with attachments in a date range."""
    from datetime import date as date_type

    settings = get_settings()
    to_day = body.to_date or date_type.today()
    try:
        job = await create_mailbox_backfill_job(
            db,
            org_id=ctx.org_id,
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

        background_tasks.add_task(run_mailbox_backfill_background, job.id)
    else:
        try:
            from app.workers.tasks import mailbox_backfill_task

            async_result = mailbox_backfill_task.delay(job.id)
            task_id = async_result.id
            job.celery_task_id = task_id
            await db.commit()
        except Exception:
            from app.workers.tasks import run_mailbox_backfill_background

            background_tasks.add_task(run_mailbox_backfill_background, job.id)

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
        job = await get_mailbox_backfill_job(db, job_id=job_id, org_id=ctx.org_id)
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
    row = await db.get(ConnectedMailbox, mailbox_id)
    if not row or row.org_id != ctx.org_id:
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
    row = await db.get(ConnectedMailbox, mailbox_id)
    if not row or row.org_id != ctx.org_id:
        raise HTTPException(404, "Mailbox not found")
    if row.auth_type != AUTH_DELEGATED:
        raise HTTPException(422, "Only OAuth-connected mailboxes can be disconnected")
    disconnect_oauth_mailbox(row)
    await db.flush()
    await db.refresh(row)
    return ApiEnvelope(data=_to_response(row))
