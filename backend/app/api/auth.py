"""Registration, login, and current user."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_user
from app.models.organisation import Organisation
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    SwitchOrgRequest,
    TokenResponse,
    UserResponse,
)
from app.services.org_membership import ensure_membership, user_has_org_access
from app.schemas.common import ApiEnvelope
from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.org_context import (
    ensure_connected_mailbox,
    get_or_create_default_org,
    sync_env_mailbox,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User, org: Organisation) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        org_id=org.id,
        org_name=org.name,
        org_slug=org.slug,
    )


@router.post("/register", response_model=ApiEnvelope[TokenResponse], status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TokenResponse]:
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    if user_count > 0:
        raise HTTPException(403, "Registration is closed. Sign in with an existing account.")

    email_taken = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if email_taken:
        raise HTTPException(409, "Email already registered")

    existing_org = (
        await db.execute(select(Organisation).where(Organisation.slug == body.org_slug))
    ).scalar_one_or_none()
    if existing_org:
        org = existing_org
        if body.org_name.strip():
            org.name = body.org_name.strip()
    else:
        org = Organisation(name=body.org_name, slug=body.org_slug)
        db.add(org)
        await db.flush()

    user = User(
        org_id=org.id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.flush()
    await ensure_membership(db, user_id=user.id, org_id=org.id)
    await sync_env_mailbox(db, org.id)
    await ensure_connected_mailbox(db, org.id, user.email, display_name=user.full_name)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        org_slug=org.slug,
        email=user.email,
        role=user.role.value,
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=token,
            user=_user_response(user, org),
        )
    )


@router.post("/login", response_model=ApiEnvelope[TokenResponse])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TokenResponse]:
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")

    org = await db.get(Organisation, user.org_id)
    if not org:
        raise HTTPException(500, "User organisation missing")

    await ensure_connected_mailbox(db, org.id, user.email, display_name=user.full_name)

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        org_slug=org.slug,
        email=user.email,
        role=user.role.value,
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=token,
            user=_user_response(user, org),
        )
    )


@router.post("/switch-org", response_model=ApiEnvelope[TokenResponse])
async def switch_organisation(
    body: SwitchOrgRequest,
    db: AsyncSession = Depends(get_db),
    ctx=Depends(require_user),
) -> ApiEnvelope[TokenResponse]:
    """Switch active tenant (demo multi-org). Issues a new JWT scoped to org_id."""
    if ctx.user_id is None:
        raise HTTPException(401, "Sign in to switch organisation")

    if not await user_has_org_access(db, user_id=ctx.user_id, org_id=body.org_id):
        raise HTTPException(403, "You do not have access to this organisation")

    user = await db.get(User, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Session invalid")

    org = await db.get(Organisation, body.org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")

    user.org_id = org.id
    await db.flush()

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        org_slug=org.slug,
        email=user.email,
        role=user.role.value,
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=token,
            user=_user_response(user, org),
        )
    )


@router.post("/refresh", response_model=ApiEnvelope[TokenResponse])
async def refresh_session(
    ctx=Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[TokenResponse]:
    """Issue a new JWT while the current one is still valid (extends active sessions)."""
    if ctx.user_id is None:
        raise HTTPException(401, "Authentication required")

    user = await db.get(User, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Session invalid")

    org = await db.get(Organisation, ctx.org_id)
    if not org:
        raise HTTPException(500, "Organisation missing")

    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        org_slug=org.slug,
        email=user.email,
        role=user.role.value,
    )
    return ApiEnvelope(
        data=TokenResponse(
            access_token=token,
            user=_user_response(user, org),
        )
    )


@router.get("/me", response_model=ApiEnvelope[UserResponse])
async def me(
    ctx=Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[UserResponse]:
    org = await db.get(Organisation, ctx.org_id)
    if not org:
        raise HTTPException(500, "Organisation missing")
    if ctx.user_id is None:
        return ApiEnvelope(
            data=UserResponse(
                id=0,
                email=ctx.email,
                full_name="System",
                role=ctx.role,
                org_id=org.id,
                org_name=org.name,
                org_slug=org.slug,
            )
        )
    user = await db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(401, "Session invalid")
    return ApiEnvelope(data=_user_response(user, org))


@router.post("/logout", response_model=ApiEnvelope[dict[str, str]])
async def logout() -> ApiEnvelope[dict[str, str]]:
    return ApiEnvelope(data={"message": "Signed out. Discard the client token."})
