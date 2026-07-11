"""Self-service signup wizard API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_preauth_db
from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.schemas.signup import (
    SignupCheckoutResponse,
    SignupCompleteResponse,
    SignupLinkResponse,
    SignupOrganizationRequest,
    SignupRegisterRequest,
    SignupSelectPlanRequest,
    SignupSessionInfo,
    SignupVerifyOtpRequest,
)
from app.services.auth.auth_email_service import send_login_otp_email
from app.services.auth.auth_service import (
    TOKEN_TYPE_SIGNUP_EMAIL_CHALLENGE,
    TOKEN_TYPE_SIGNUP_SESSION,
    create_signup_email_challenge_token,
    create_signup_session_token,
    decode_token,
    hash_password,
)
from app.services.auth.auth_session_service import generate_otp
from app.services.credit_catalog import (
    PLAN_FREE,
    PLAN_STUDIO,
    plan_definition,
    pricing_region_for_country,
)
from app.services.payments.stripe_platform_billing_service import (
    create_wizard_signup_checkout,
    fulfill_signup_checkout_session,
)
from app.services.signup.signup_fulfillment_service import (
    ensure_pending_auth_account,
    is_oauth_only_auth_account,
    oauth_placeholder_password_hash,
    slugify_organization_name,
)
from app.services.signup.signup_login_service import (
    mint_auth_for_provisioned_tenant,
    mint_signup_session_auth,
)
from app.services.signup.signup_session_service import (
    SignupSession,
    clear_signup_otp,
    delete_signup_session,
    load_signup_session,
    new_session_id,
    pop_register_meta,
    save_signup_session,
    store_register_meta,
    store_signup_otp,
    verify_signup_otp,
)
from app.services.auth.auth_account_service import resolve_login_account
from app.services.shared.public_app_url import build_oauth_frontend_path
from app.tenant_settings import COUNTRY_DEFAULTS, DEFAULT_COUNTRY
from app.utils.logger import get_logger

router = APIRouter(prefix="/signup", tags=["signup"])
_bearer = HTTPBearer(auto_error=False)
logger = get_logger(__name__)

PUBLIC_SIGNUP_PATH = "/signup"
PUBLIC_SIGNUP_ALIASES = ("/start", "/get-started", "/register")


@router.get("/link", response_model=ApiEnvelope[SignupLinkResponse])
async def get_public_signup_link() -> ApiEnvelope[SignupLinkResponse]:
    """Public embeddable signup URL for marketing sites and partner pages."""
    url = build_oauth_frontend_path(PUBLIC_SIGNUP_PATH)
    return ApiEnvelope(
        data=SignupLinkResponse(
            path=PUBLIC_SIGNUP_PATH,
            url=url,
            aliases=list(PUBLIC_SIGNUP_ALIASES),
            embed_html=f'<a href="{url}">Get started with Ledgerline</a>',
        )
    )


def _require_signup_session_token(
    creds: HTTPAuthorizationCredentials | None,
) -> str:
    if not creds or not creds.credentials:
        raise HTTPException(401, "Signup session required")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != TOKEN_TYPE_SIGNUP_SESSION:
        raise HTTPException(401, "Invalid signup session")
    return str(payload["sub"])


async def _load_session_or_404(session_id: str) -> SignupSession:
    signup = await load_signup_session(session_id)
    if not signup:
        raise HTTPException(404, "Signup session expired — please start again")
    return signup


def _session_info(signup: SignupSession) -> SignupSessionInfo:
    return SignupSessionInfo(
        email=signup.email,
        full_name=signup.full_name,
        provider=signup.provider,
        status=signup.status,
        organization_name=signup.organization_name,
        country=signup.country,
        industry=signup.industry,
        phone=signup.phone,
        plan=signup.plan,
        identity_via_oauth=signup.provider in ("google", "microsoft"),
    )


@router.get("/session", response_model=ApiEnvelope[SignupSessionInfo])
async def get_signup_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[SignupSessionInfo]:
    session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(session_id)
    return ApiEnvelope(data=_session_info(signup))


@router.post("/register", response_model=ApiEnvelope[dict])
async def signup_register(
    body: SignupRegisterRequest,
    db: AsyncSession = Depends(get_preauth_db),
) -> ApiEnvelope[dict]:
    email = body.email.lower().strip()
    existing = await resolve_login_account(db, email)
    if existing and not is_oauth_only_auth_account(existing.password_hash):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")

    settings = get_settings()
    password_hash = hash_password(body.password)
    await store_register_meta(
        email=email,
        password_hash=password_hash,
        full_name=body.full_name.strip(),
    )

    otp = generate_otp()
    await store_signup_otp(
        email=email,
        otp=otp,
        ttl_seconds=settings.otp_expire_minutes * 60,
    )
    delivery = await send_login_otp_email(to_email=email, otp=otp)
    if not delivery.sent:
        await clear_signup_otp(email=email)
        raise HTTPException(503, "Could not send verification email")

    challenge = create_signup_email_challenge_token(email=email)
    return ApiEnvelope(
        data={
            "challenge_token": challenge,
            "message": "Verification code sent to your email",
        }
    )


@router.post("/verify-otp", response_model=ApiEnvelope[dict])
async def signup_verify_otp(
    body: SignupVerifyOtpRequest,
    db: AsyncSession = Depends(get_preauth_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[dict]:
    if not creds or not creds.credentials:
        raise HTTPException(401, "Challenge token required")
    payload = decode_token(creds.credentials)
    if not payload or payload.get("type") != TOKEN_TYPE_SIGNUP_EMAIL_CHALLENGE:
        raise HTTPException(401, "Invalid challenge token")

    email = str(payload["email"]).lower()
    if not await verify_signup_otp(email=email, otp=body.otp):
        raise HTTPException(401, "Invalid verification code")
    await clear_signup_otp(email=email)

    meta = await pop_register_meta(email)
    if not meta:
        raise HTTPException(400, "Registration expired — please start again")

    account = await ensure_pending_auth_account(
        db,
        email=email,
        password_hash=str(meta["password_hash"]),
    )
    await db.commit()

    session_id = new_session_id()
    signup = SignupSession(
        session_id=session_id,
        email=email,
        full_name=str(meta.get("full_name") or ""),
        provider="email",
        status="organization",
        password_hash=str(meta["password_hash"]),
        auth_account_id=account.id,
    )
    await save_signup_session(signup)
    signup_token = create_signup_session_token(session_id=session_id)
    return ApiEnvelope(data={"signup_token": signup_token})


@router.post("/organization", response_model=ApiEnvelope[SignupSessionInfo])
async def signup_organization(
    body: SignupOrganizationRequest,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[SignupSessionInfo]:
    session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(session_id)
    org_name = body.organization_name.strip()
    country = body.country.strip().upper()
    if country not in COUNTRY_DEFAULTS:
        raise HTTPException(400, "Unsupported country")
    signup.organization_name = org_name
    signup.organization_slug = slugify_organization_name(org_name)
    signup.country = country
    if body.industry:
        signup.industry = body.industry.strip()
    if body.phone:
        signup.phone = body.phone.strip()
    signup.status = "plan"
    await save_signup_session(signup)
    return ApiEnvelope(data=_session_info(signup))


@router.get("/plans", response_model=ApiEnvelope[list[dict]])
async def signup_plans(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[list[dict]]:
    session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(session_id)
    country = (signup.country or DEFAULT_COUNTRY).strip().upper()
    options = []
    for plan_key, label in [(PLAN_FREE, "Free"), (PLAN_STUDIO, "Studio")]:
        definition = plan_definition(country_code=country, plan=plan_key)
        options.append(
            {
                "plan": plan_key,
                "label": label,
                "monthly_credits": definition.monthly_credits,
                "max_users": definition.max_users,
                "monthly_price": float(definition.monthly_price),
                "currency_code": definition.currency_code,
                "social_integration": definition.social_integration,
                "email_integration": definition.email_integration,
                "country": country,
                "pricing_region": pricing_region_for_country(country),
            }
        )
    return ApiEnvelope(data=options)


@router.post("/select-plan", response_model=ApiEnvelope[SignupSessionInfo])
async def signup_select_plan(
    body: SignupSelectPlanRequest,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiEnvelope[SignupSessionInfo]:
    session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(session_id)
    if not signup.organization_name:
        raise HTTPException(400, "Organization name is required first")
    signup.plan = body.plan
    signup.status = "payment" if body.plan == PLAN_STUDIO else "provisioning"
    await save_signup_session(signup)
    return ApiEnvelope(data=_session_info(signup))


@router.post("/checkout", response_model=ApiEnvelope[SignupCheckoutResponse])
async def signup_checkout(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[SignupCheckoutResponse]:
    session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(session_id)
    if signup.plan != PLAN_STUDIO:
        raise HTTPException(400, "Checkout is only required for Studio plan")
    if not signup.organization_name or not signup.country:
        raise HTTPException(400, "Organization details are required before checkout")

    result = await create_wizard_signup_checkout(db, signup=signup)
    signup.stripe_session_id = result.session_id
    signup.status = "payment"
    await save_signup_session(signup)
    await db.commit()

    if not result.checkout_url or not result.session_id:
        raise HTTPException(502, "Stripe checkout is temporarily unavailable")
    return ApiEnvelope(
        data=SignupCheckoutResponse(
            checkout_url=result.checkout_url,
            session_id=result.session_id,
        )
    )


@router.post("/complete-studio", response_model=ApiEnvelope[SignupCompleteResponse])
async def signup_complete_studio(
    session_id: str,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[SignupCompleteResponse]:
    signup_session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(signup_session_id)
    if signup.plan != PLAN_STUDIO:
        raise HTTPException(400, "Studio plan required")

    try:
        status = await fulfill_signup_checkout_session(db, session_id=session_id)
        pending_email = str(status.get("email") or "").lower()
        if pending_email and pending_email != signup.email.lower():
            raise HTTPException(400, "Invalid payment session")
        if status.get("payment_status") != "paid" or not status.get("tenant_id"):
            raise HTTPException(
                409, "Payment is still processing — please wait a moment and try again"
            )

        signup.stripe_session_id = session_id
        signup.status = "provisioning"
        await save_signup_session(signup)

        payload = await mint_auth_for_provisioned_tenant(
            db,
            tenant_id=status["tenant_id"],
            email=signup.email,
        )
        await delete_signup_session(signup.session_id)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    return ApiEnvelope(
        data=SignupCompleteResponse(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            redirect_to=payload["redirect_to"],
            user=payload["user"],
        )
    )


@router.post("/confirm-payment", response_model=ApiEnvelope[SignupCompleteResponse])
async def signup_confirm_payment(
    session_id: str,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[SignupCompleteResponse]:
    """Legacy alias for Studio checkout completion after Stripe redirect."""
    return await signup_complete_studio(session_id=session_id, creds=creds, db=db)


@router.post("/complete-free", response_model=ApiEnvelope[SignupCompleteResponse])
async def signup_complete_free(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[SignupCompleteResponse]:
    signup_session_id = _require_signup_session_token(creds)
    signup = await _load_session_or_404(signup_session_id)
    if signup.plan != PLAN_FREE:
        raise HTTPException(400, "Free plan provisioning only")
    signup.status = "provisioning"
    await save_signup_session(signup)
    payload = await mint_signup_session_auth(db, signup=signup)
    await db.commit()
    return ApiEnvelope(
        data=SignupCompleteResponse(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            redirect_to=payload["redirect_to"],
            user=payload["user"],
        )
    )
