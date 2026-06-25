"""Registration, login, OTP, and session management."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_user
from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginChallengeResponse,
    LoginRequest,
    RefreshTokenRequest,
    SelectTenantRequest,
    SwitchTenantRequest,
    TenantAccountSummary,
    TokenResponse,
    UserResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.schemas.tenant_member import (
    InviteAcceptRequest,
    InviteAcceptResponse,
    InvitePreviewResponse,
    PermissionsResponse,
)
from app.schemas.common import ApiEnvelope
from app.services.auth_account_service import resolve_login_account
from app.services.auth_email_service import send_login_otp_email
from app.services.auth_service import (
    TOKEN_TYPE_CHALLENGE,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_TENANT_SELECT,
    create_access_token,
    create_challenge_token,
    create_refresh_token,
    create_tenant_select_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.auth_session_service import (
    clear_otp,
    generate_otp,
    is_user_revoked,
    new_jti,
    register_refresh_session,
    revoke_refresh_jti,
    store_otp,
    validate_refresh_jti,
    verify_otp,
)
from app.services.membership_enumeration import (
    filter_switchable_memberships,
    list_memberships_for_auth_account,
    membership_is_switchable,
)
from app.services.membership_service import ensure_membership, user_has_tenant_access
from app.services.privilege_service import matrix_role_for_context, permissions_for_context
from app.services.tenant_module_service import enabled_modules_map
from app.services.tenant_context_service import get_tenant_slug
from app.services.tenant_members_service import accept_invite, preview_invite
from app.tenant_ids import parse_tenant_id
from app.tenant_context import set_jwt_tenant_id, set_request_tenant_id
from app.tenant_rls import apply_rls_session_context
from app.tenant_settings import tenant_locale, tenant_onboarding_completed, tenant_timezone

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _user_response(
    user: User,
    tenant: Tenant,
    *,
    role: str | None = None,
    is_support_session: bool = False,
    onboarding_completed: bool | None = None,
) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role or user.role.value,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        tenant_timezone=tenant_timezone(tenant),
        tenant_locale=tenant_locale(tenant),
        is_support_session=is_support_session,
        onboarding_completed=(
            tenant_onboarding_completed(tenant)
            if onboarding_completed is None
            else onboarding_completed
        ),
    )


def _account_summary_from_membership(m) -> TenantAccountSummary:
    return TenantAccountSummary(
        user_id=m.user_id,
        tenant_id=m.tenant_id,
        tenant_name=m.tenant_name,
        tenant_slug=m.tenant_slug,
        role=m.role,
        default_tenant=m.default_tenant,
        is_platform=m.is_platform,
    )


async def _membership_summaries_for_account(
    db: AsyncSession, *, auth_account_id: int
) -> list[TenantAccountSummary]:
    memberships = await list_memberships_for_auth_account(db, auth_account_id=auth_account_id)
    switchable = filter_switchable_memberships(memberships)
    return [_account_summary_from_membership(m) for m in switchable]


async def _resolve_switch_target(
    db: AsyncSession,
    *,
    auth_account_id: int,
    target_tenant_id: uuid.UUID,
) -> tuple[User, Tenant, str]:
    memberships = await list_memberships_for_auth_account(db, auth_account_id=auth_account_id)
    match = next((m for m in memberships if m.tenant_id == target_tenant_id), None)
    if not match:
        raise HTTPException(403, "You do not have access to this tenant")
    if not membership_is_switchable(match):
        raise HTTPException(403, "Platform tenant access requires super admin")

    user = await db.get(User, match.user_id)
    tenant = await db.get(Tenant, match.tenant_id)
    if not user or not tenant or not user.is_active:
        raise HTTPException(403, "Account inactive")
    if user.is_platform_shadow:
        raise HTTPException(
            403,
            "Client tenant support access must be opened from the platform console",
        )
    if not tenant.is_active or tenant.lifecycle_status != "active":
        raise HTTPException(403, "Tenant access suspended")
    return user, tenant, match.role


async def _mint_session_tokens(
    db: AsyncSession,
    *,
    user: User,
    tenant: Tenant,
    role: str,
    is_support_session: bool = False,
) -> tuple[str, str]:
    from app.config import get_settings

    settings = get_settings()
    jti = new_jti()
    slug = tenant.slug
    access = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=slug,
        email=user.email,
        role=role,
        is_support_session=is_support_session,
    )
    refresh = create_refresh_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=slug,
        email=user.email,
        role=role,
        jti=jti,
        is_support_session=is_support_session,
    )
    await register_refresh_session(
        jti=jti,
        user_id=user.id,
        tenant_id=tenant.id,
        ttl_days=settings.refresh_token_expire_days,
    )
    return access, refresh


def _require_token_type(creds: HTTPAuthorizationCredentials | None, expected: str) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(401, "Authentication required")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != expected:
        raise HTTPException(401, "Invalid token")
    return payload


@router.post("/login", response_model=ApiEnvelope[LoginChallengeResponse])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[LoginChallengeResponse]:
    from app.config import get_settings

    settings = get_settings()
    account = await resolve_login_account(db, body.email)
    if not account or account.is_blocked:
        raise HTTPException(401, "Invalid email or password")
    if not verify_password(body.password, account.password_hash):
        raise HTTPException(401, "Invalid email or password")

    otp = generate_otp()
    await store_otp(
        auth_account_id=account.id,
        email=account.email,
        otp=otp,
        ttl_seconds=settings.otp_expire_minutes * 60,
    )
    await send_login_otp_email(to_email=account.email, otp=otp)

    token = create_challenge_token(auth_account_id=account.id, email=account.email)
    return ApiEnvelope(
        data=LoginChallengeResponse(challenge_token=token),
    )


@router.post("/verify-otp", response_model=ApiEnvelope[VerifyOtpResponse])
async def verify_otp_endpoint(
    body: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[VerifyOtpResponse]:
    payload = _require_token_type(creds, TOKEN_TYPE_CHALLENGE)
    auth_account_id = int(payload["sub"])
    email = str(payload["email"])

    account = await db.get(AuthAccount, auth_account_id)
    if not account or account.is_blocked:
        raise HTTPException(401, "Invalid session")

    if not await verify_otp(auth_account_id=account.id, email=email, otp=body.otp):
        raise HTTPException(401, "Invalid verification code")

    await clear_otp(auth_account_id=account.id, email=email)
    memberships = filter_switchable_memberships(
        await list_memberships_for_auth_account(db, auth_account_id=account.id)
    )
    if not memberships:
        raise HTTPException(403, "No tenant access for this account")

    if len(memberships) == 1:
        m = memberships[0]
        user = await db.get(User, m.user_id)
        tenant = await db.get(Tenant, m.tenant_id)
        if not user or not tenant or not user.is_active:
            raise HTTPException(403, "Account inactive")
        access, refresh = await _mint_session_tokens(db, user=user, tenant=tenant, role=m.role)
        return ApiEnvelope(
            data=VerifyOtpResponse(
                multi_tenant=False,
                access_token=access,
                refresh_token=refresh,
                user=_user_response(user, tenant, role=m.role),
            )
        )

    select_token = create_tenant_select_token(auth_account_id=account.id, email=email)
    return ApiEnvelope(
        data=VerifyOtpResponse(
            multi_tenant=True,
            tenant_select_token=select_token,
            accounts=[_account_summary_from_membership(m) for m in memberships],
        )
    )


@router.post("/resend-otp", response_model=ApiEnvelope[LoginChallengeResponse])
async def resend_otp(
    db: AsyncSession = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[LoginChallengeResponse]:
    from app.config import get_settings

    settings = get_settings()
    payload = _require_token_type(creds, TOKEN_TYPE_CHALLENGE)
    auth_account_id = int(payload["sub"])
    email = str(payload["email"])
    account = await db.get(AuthAccount, auth_account_id)
    if not account:
        raise HTTPException(401, "Invalid session")

    otp = generate_otp()
    await store_otp(
        auth_account_id=account.id,
        email=account.email,
        otp=otp,
        ttl_seconds=settings.otp_expire_minutes * 60,
    )
    await send_login_otp_email(to_email=account.email, otp=otp)
    token = create_challenge_token(auth_account_id=account.id, email=account.email)
    return ApiEnvelope(data=LoginChallengeResponse(challenge_token=token))


@router.post("/select-tenant", response_model=ApiEnvelope[TokenResponse])
async def select_tenant(
    body: SelectTenantRequest,
    db: AsyncSession = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[TokenResponse]:
    payload = _require_token_type(creds, TOKEN_TYPE_TENANT_SELECT)
    auth_account_id = int(payload["sub"])
    memberships = filter_switchable_memberships(
        await list_memberships_for_auth_account(db, auth_account_id=auth_account_id)
    )
    match = next((m for m in memberships if m.tenant_id == body.tenant_id), None)
    if not match:
        raise HTTPException(403, "You do not have access to this tenant")

    user = await db.get(User, match.user_id)
    tenant = await db.get(Tenant, match.tenant_id)
    if not user or not tenant:
        raise HTTPException(404, "Tenant not found")

    access, refresh = await _mint_session_tokens(db, user=user, tenant=tenant, role=match.role)
    memberships = await _membership_summaries_for_account(
        db, auth_account_id=auth_account_id
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=access,
            refresh_token=refresh,
            user=_user_response(user, tenant, role=match.role),
            memberships=memberships,
        )
    )


@router.post("/switch-tenant", response_model=ApiEnvelope[TokenResponse])
async def switch_tenant(
    body: SwitchTenantRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_user),
) -> ApiEnvelope[TokenResponse]:
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to switch tenant")

    account = (
        await db.execute(
            select(AuthAccount)
            .join(User, User.auth_account_id == AuthAccount.id)
            .where(User.id == ctx.user_id)
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(401, "Session invalid")

    user, tenant, role = await _resolve_switch_target(
        db,
        auth_account_id=account.id,
        target_tenant_id=body.tenant_id,
    )

    access, refresh = await _mint_session_tokens(db, user=user, tenant=tenant, role=role)
    memberships = await _membership_summaries_for_account(db, auth_account_id=account.id)
    return ApiEnvelope(
        data=TokenResponse(
            access_token=access,
            refresh_token=refresh,
            user=_user_response(user, tenant, role=role),
            memberships=memberships,
        )
    )


@router.post("/refresh", response_model=ApiEnvelope[TokenResponse])
async def refresh_session(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TokenResponse]:
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != TOKEN_TYPE_REFRESH:
        raise HTTPException(401, "Invalid refresh token")

    jti = str(payload.get("jti", ""))
    stored = await validate_refresh_jti(jti)
    if not stored:
        raise HTTPException(401, "Refresh session expired")

    user_id = int(payload["sub"])
    tenant_id = parse_tenant_id(payload.get("tenant_id"))
    if tenant_id is None:
        raise HTTPException(401, "Invalid refresh token")
    set_jwt_tenant_id(tenant_id)
    set_request_tenant_id(tenant_id)
    await apply_rls_session_context(db, tenant_id)
    if await is_user_revoked(user_id):
        raise HTTPException(401, "Session revoked")

    user = await db.get(User, user_id)
    tenant = await db.get(Tenant, tenant_id)
    if not user or not tenant or not user.is_active:
        raise HTTPException(401, "Session invalid")

    if not await user_has_tenant_access(db, user_id=user_id, tenant_id=tenant_id):
        raise HTTPException(403, "Tenant access revoked")

    await revoke_refresh_jti(jti)
    role = str(payload.get("role", user.role.value))
    is_support = bool(payload.get("is_support_session"))
    access, refresh = await _mint_session_tokens(
        db, user=user, tenant=tenant, role=role, is_support_session=is_support
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=access,
            refresh_token=refresh,
            user=_user_response(
                user, tenant, role=role, is_support_session=is_support
            ),
        )
    )


@router.post("/logout", response_model=ApiEnvelope[dict[str, str]])
async def logout(body: RefreshTokenRequest | None = None) -> ApiEnvelope[dict[str, str]]:
    if body and body.refresh_token:
        payload = decode_token(body.refresh_token)
        if payload and payload.get("jti"):
            await revoke_refresh_jti(str(payload["jti"]))
    return ApiEnvelope(data={"message": "Signed out"})


@router.get("/me", response_model=ApiEnvelope[UserResponse])
async def me(
    ctx: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[UserResponse]:
    tenant = await db.get(Tenant, ctx.tenant_id)
    if not tenant:
        raise HTTPException(500, "Tenant missing")
    if ctx.user_id is None:
        return ApiEnvelope(
            data=UserResponse(
                id=0,
                email=ctx.email,
                full_name="System",
                role=ctx.role,
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                tenant_timezone=tenant_timezone(tenant),
                tenant_locale=tenant_locale(tenant),
            )
        )
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(401, "Session invalid")
    return ApiEnvelope(
        data=_user_response(
            user,
            tenant,
            role=ctx.role,
            is_support_session=ctx.is_support_session,
        )
    )


@router.get("/me/memberships", response_model=ApiEnvelope[list[TenantAccountSummary]])
async def my_memberships(
    ctx: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[list[TenantAccountSummary]]:
    if ctx.user_id is None:
        raise HTTPException(401, "Authentication required")
    user = await db.get(User, ctx.user_id)
    if not user or not user.auth_account_id:
        raise HTTPException(401, "Session invalid")
    memberships = filter_switchable_memberships(
        await list_memberships_for_auth_account(
            db, auth_account_id=user.auth_account_id
        )
    )
    return ApiEnvelope(
        data=[_account_summary_from_membership(m) for m in memberships],
    )


@router.get("/me/permissions", response_model=ApiEnvelope[PermissionsResponse])
async def my_permissions(
    ctx: AuthContext = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[PermissionsResponse]:
    modules = await enabled_modules_map(db, ctx.tenant_id)
    return ApiEnvelope(
        data=PermissionsResponse(
            role=ctx.role,
            matrix_role=matrix_role_for_context(ctx),
            permissions=permissions_for_context(ctx),
            enabled_modules=modules,
        )
    )


@router.get("/invite/preview", response_model=ApiEnvelope[InvitePreviewResponse])
async def invite_preview(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[InvitePreviewResponse]:
    preview = await preview_invite(db, token=token)
    return ApiEnvelope(
        data=InvitePreviewResponse(
            email=preview.email,
            full_name=preview.full_name,
            role=preview.role,
            tenant_name=preview.tenant_name,
            tenant_slug=preview.tenant_slug,
            expired=preview.expired,
            accepted=preview.accepted,
        )
    )


@router.post("/invite/accept", response_model=ApiEnvelope[InviteAcceptResponse])
async def invite_accept(
    body: InviteAcceptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[InviteAcceptResponse]:
    from app.services.audit_service import log_event

    user, tenant, role = await accept_invite(
        db,
        token=body.token,
        password=body.password,
        full_name=body.full_name,
    )
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "tenant_member_invite_accepted",
        tenant_id=tenant.id,
        detail={"user_id": user.id, "email": user.email, "role": role},
        actor_name=user.full_name,
        actor_email=user.email,
        client_ip=client_ip,
    )
    return ApiEnvelope(
        data=InviteAcceptResponse(
            message="Invitation accepted. You can sign in with your email and password.",
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            email=user.email,
        )
    )
