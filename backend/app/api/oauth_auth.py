"""Google / Microsoft OAuth routes for dashboard login and signup."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_preauth_db
from app.config import get_settings
from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.common import ApiEnvelope
from app.schemas.signup import (
    MicrosoftCompleteRequest,
    MicrosoftPrepareResponse,
    OAuthFlowResult,
    OAuthProvidersResponse,
)
from app.services.auth.auth_service import (
    TOKEN_TYPE_TENANT_SELECT,
    create_signup_session_token,
    create_tenant_select_token,
)
from app.services.auth.membership_enumeration import (
    filter_switchable_memberships,
    list_memberships_for_auth_account,
)
from app.services.auth.oauth_login_service import (
    OAuthIdentity,
    exchange_google_code,
    exchange_microsoft_code_confidential,
    google_oauth_login_configured,
    identity_from_microsoft_complete,
    microsoft_oauth_login_configured,
    parse_oauth_state,
    prepare_google_oauth,
    prepare_microsoft_oauth,
)
from app.services.shared.public_app_url import build_oauth_frontend_path
from app.services.signup.signup_fulfillment_service import (
    ensure_pending_auth_account,
    oauth_placeholder_password_hash,
)
from app.services.signup.signup_session_service import (
    SignupSession,
    new_session_id,
    save_signup_session,
)
from app.api.auth import (
    _account_summary_from_membership,
    _membership_summaries_for_account,
    _mint_session_tokens,
    _user_response,
)
from app.utils.logger import get_logger

router = APIRouter(prefix="/auth/oauth", tags=["oauth-auth"])
logger = get_logger(__name__)

OAuthIntent = Literal["signup", "login"]


def _frontend_oauth_callback_url(**params: str) -> str:
    base = build_oauth_frontend_path("/login/oauth/callback")
    if not params:
        return base
    url = f"{base}?{urlencode(params)}"
    logger.info("oauth_frontend_redirect", target=url.split("?")[0], params=list(params.keys()))
    return url


def _signup_redirect(signup_token: str) -> str:
    return f"{build_oauth_frontend_path('/signup')}?token={signup_token}"


async def _resolve_oauth_identity(
    db: AsyncSession,
    *,
    identity: OAuthIdentity,
    intent: OAuthIntent,
) -> OAuthFlowResult:
    email = identity.email.lower().strip()
    account = (
        await db.execute(select(AuthAccount).where(AuthAccount.email == email))
    ).scalar_one_or_none()

    if intent == "login":
        if not account:
            return OAuthFlowResult(result="error", error="no_account")
        if account.is_blocked:
            return OAuthFlowResult(result="error", error="no_account")

        memberships = filter_switchable_memberships(
            await list_memberships_for_auth_account(
                db, auth_account_id=account.id, log_source="oauth_login"
            )
        )
        if not memberships:
            return OAuthFlowResult(result="error", error="no_account")

        if len(memberships) == 1:
            m = memberships[0]
            user = await db.get(User, m.user_id)
            tenant = await db.get(Tenant, m.tenant_id)
            if not user or not tenant or not user.is_active:
                return OAuthFlowResult(result="error", error="no_account")
            access, refresh = await _mint_session_tokens(
                db, user=user, tenant=tenant, role=m.role
            )
            return OAuthFlowResult(
                result="login",
                access_token=access,
                refresh_token=refresh,
            )

        select_token = create_tenant_select_token(auth_account_id=account.id, email=email)
        accounts = [
            _account_summary_from_membership(m).model_dump() for m in memberships
        ]
        return OAuthFlowResult(
            result="tenant_select",
            tenant_select_token=select_token,
            accounts=accounts,
        )

    # signup
    password_hash = oauth_placeholder_password_hash()
    if not account:
        account = await ensure_pending_auth_account(
            db, email=email, password_hash=password_hash
        )
    elif account.password_hash != oauth_placeholder_password_hash():
        existing_memberships = await list_memberships_for_auth_account(
            db, auth_account_id=account.id, log_source="oauth_signup"
        )
        if existing_memberships:
            return OAuthFlowResult(result="error", error="account_exists")

    session_id = new_session_id()
    signup = SignupSession(
        session_id=session_id,
        email=email,
        full_name=identity.name,
        provider=identity.provider,
        status="organization",
        password_hash=password_hash,
        auth_account_id=account.id,
    )
    await save_signup_session(signup)
    signup_token = create_signup_session_token(session_id=session_id)
    return OAuthFlowResult(result="signup", signup_token=signup_token)


async def _flow_result_from_identity(
    db: AsyncSession,
    *,
    identity: OAuthIdentity,
    intent: OAuthIntent,
) -> OAuthFlowResult:
    result = await _resolve_oauth_identity(db, identity=identity, intent=intent)
    await db.commit()
    return result


def _redirect_for_flow_result(result: OAuthFlowResult) -> RedirectResponse:
    if result.result == "login" and result.access_token and result.refresh_token:
        return RedirectResponse(
            _frontend_oauth_callback_url(
                access_token=result.access_token,
                refresh_token=result.refresh_token,
            )
        )
    if result.result == "signup" and result.signup_token:
        return RedirectResponse(_signup_redirect(result.signup_token))
    if result.result == "tenant_select" and result.tenant_select_token:
        return RedirectResponse(
            _frontend_oauth_callback_url(
                tenant_select_token=result.tenant_select_token,
            )
        )
    error = result.error or "oauth_failed"
    return RedirectResponse(_frontend_oauth_callback_url(error=error))


@router.get("/providers", response_model=ApiEnvelope[OAuthProvidersResponse])
async def oauth_providers() -> ApiEnvelope[OAuthProvidersResponse]:
    settings = get_settings()
    logger.info(
        "oauth_providers_status",
        google_configured=google_oauth_login_configured(),
        microsoft_configured=microsoft_oauth_login_configured(),
        microsoft_public_client=settings.microsoft_oauth_public_client,
        microsoft_redirect_uri=settings.microsoft_oauth_redirect_uri,
        google_redirect_uri=settings.google_oauth_login_redirect_uri,
        microsoft_client_id_prefix=settings.microsoft_oauth_client_id[:8]
        if settings.microsoft_oauth_client_id
        else "",
    )
    return ApiEnvelope(
        data=OAuthProvidersResponse(
            google=google_oauth_login_configured(),
            microsoft=microsoft_oauth_login_configured(),
            microsoft_public_client=settings.microsoft_oauth_public_client,
        )
    )


@router.get("/google/start")
async def google_oauth_start(
    intent: OAuthIntent = Query("login"),
) -> RedirectResponse:
    if not google_oauth_login_configured():
        raise HTTPException(503, "Google sign-in is not configured")
    url, _state = prepare_google_oauth(intent)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_preauth_db),
) -> RedirectResponse:
    if error or not code or not state:
        return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))
    try:
        payload = parse_oauth_state(state)
        if payload.get("provider") != "google":
            raise ValueError("Invalid provider")
        intent: OAuthIntent = payload.get("intent") or "login"
        pkce = str(payload.get("pkce") or "")
        identity = await exchange_google_code(code=code, pkce_verifier=pkce)
        result = await _flow_result_from_identity(db, identity=identity, intent=intent)
        return _redirect_for_flow_result(result)
    except Exception as exc:
        logger.warning("google_oauth_callback_failed", error=str(exc))
        return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))


@router.get("/microsoft/prepare", response_model=ApiEnvelope[MicrosoftPrepareResponse])
async def microsoft_oauth_prepare(
    intent: OAuthIntent = Query("login"),
) -> ApiEnvelope[MicrosoftPrepareResponse]:
    if not microsoft_oauth_login_configured():
        raise HTTPException(503, "Microsoft sign-in is not configured")
    settings = get_settings()
    prepared = prepare_microsoft_oauth(intent)
    logger.info(
        "microsoft_oauth_prepare",
        intent=intent,
        public_client=settings.microsoft_oauth_public_client,
        redirect_uri=prepared.redirect_uri,
        client_id_prefix=prepared.client_id[:8] if prepared.client_id else "",
    )
    return ApiEnvelope(
        data=MicrosoftPrepareResponse(
            authorize_url=prepared.authorize_url,
            pkce_verifier=prepared.pkce_verifier,
            client_id=prepared.client_id,
            redirect_uri=prepared.redirect_uri,
            token_url=prepared.token_url,
        )
    )


@router.get("/microsoft/start")
async def microsoft_oauth_start(
    intent: OAuthIntent = Query("login"),
) -> RedirectResponse:
    settings = get_settings()
    if not microsoft_oauth_login_configured():
        raise HTTPException(503, "Microsoft sign-in is not configured")
    if settings.microsoft_oauth_public_client:
        raise HTTPException(400, "Use /microsoft/prepare for SPA Microsoft login")
    prepared = prepare_microsoft_oauth(intent)
    logger.info(
        "microsoft_oauth_start_confidential",
        intent=intent,
        redirect_uri=prepared.redirect_uri,
    )
    return RedirectResponse(prepared.authorize_url)


@router.get("/microsoft/callback")
async def microsoft_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_preauth_db),
) -> RedirectResponse:
    if error:
        logger.warning(
            "microsoft_oauth_callback_provider_error",
            error=error,
            error_description=(error_description or "")[:300],
        )
        return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))
    if not code or not state:
        logger.warning("microsoft_oauth_callback_missing_params", has_code=bool(code), has_state=bool(state))
        return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))

    settings = get_settings()
    logger.info(
        "microsoft_oauth_callback_received",
        public_client=settings.microsoft_oauth_public_client,
        redirect_uri_configured=settings.microsoft_oauth_redirect_uri,
    )
    if settings.microsoft_oauth_public_client:
        try:
            payload = parse_oauth_state(state)
            logger.info(
                "microsoft_oauth_callback_spa_forward",
                intent=payload.get("intent"),
                forward_to_frontend=True,
            )
        except Exception as exc:
            logger.warning("microsoft_oauth_callback_invalid_state", error=str(exc))
            return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))
        return RedirectResponse(
            _frontend_oauth_callback_url(code=code, state=state, provider="microsoft")
        )

    try:
        payload = parse_oauth_state(state)
        intent: OAuthIntent = payload.get("intent") or "login"
        pkce = str(payload.get("pkce") or "")
        logger.info("microsoft_oauth_callback_confidential_exchange", intent=intent)
        identity = await exchange_microsoft_code_confidential(code=code, pkce_verifier=pkce)
        result = await _flow_result_from_identity(db, identity=identity, intent=intent)
        logger.info(
            "microsoft_oauth_callback_confidential_ok",
            intent=intent,
            result=result.result,
            email=identity.email,
        )
        return _redirect_for_flow_result(result)
    except Exception as exc:
        logger.warning("microsoft_oauth_callback_failed", error=str(exc), exc_type=type(exc).__name__)
        return RedirectResponse(_frontend_oauth_callback_url(error="oauth_failed"))


@router.post("/microsoft/complete", response_model=ApiEnvelope[OAuthFlowResult])
async def microsoft_oauth_complete(
    body: MicrosoftCompleteRequest,
    db: AsyncSession = Depends(get_preauth_db),
) -> ApiEnvelope[OAuthFlowResult]:
    try:
        payload = parse_oauth_state(body.state)
        if payload.get("provider") != "microsoft":
            raise ValueError("Invalid provider")
        intent: OAuthIntent = payload.get("intent") or "login"
        logger.info("microsoft_oauth_complete_start", intent=intent)
        identity = identity_from_microsoft_complete(id_token=body.id_token)
        result = await _flow_result_from_identity(db, identity=identity, intent=intent)
        logger.info(
            "microsoft_oauth_complete_ok",
            intent=intent,
            result=result.result,
            email=identity.email,
            error=result.error,
        )
        return ApiEnvelope(data=result)
    except Exception as exc:
        logger.warning(
            "microsoft_oauth_complete_failed",
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        return ApiEnvelope(data=OAuthFlowResult(result="error", error="oauth_failed"))
