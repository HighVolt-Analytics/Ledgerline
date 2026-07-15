"""Auth request/response schemas."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.tenant_settings import DEFAULT_LOCALE, DEFAULT_TIMEZONE


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyOtpRequest(BaseModel):
    otp: str = Field(min_length=4, max_length=8)


class SelectTenantRequest(BaseModel):
    tenant_id: UUID


class SwitchTenantRequest(BaseModel):
    tenant_id: UUID


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TenantAccountSummary(BaseModel):
    user_id: int
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: str
    default_tenant: bool = False
    is_platform: bool = False


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    tenant_timezone: str = DEFAULT_TIMEZONE
    tenant_locale: str = DEFAULT_LOCALE
    is_support_session: bool = False
    onboarding_completed: bool = True

    model_config = {"from_attributes": True}


class LoginChallengeResponse(BaseModel):
    challenge_token: str
    message: str = "Verification code sent"


class VerifyOtpResponse(BaseModel):
    multi_tenant: bool = False
    access_token: str | None = None
    refresh_token: str | None = None
    tenant_select_token: str | None = None
    accounts: list[TenantAccountSummary] = Field(default_factory=list)
    user: UserResponse | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    memberships: list[TenantAccountSummary] = Field(default_factory=list)


class PortalEmbedLoginRequest(BaseModel):
    access_token: str = Field(min_length=8)


class PortalEmbedLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    memberships: list[TenantAccountSummary] = Field(default_factory=list)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    challenge_token: str
    message: str = "Verification code sent"


class ResetPasswordRequest(BaseModel):
    challenge_token: str = Field(min_length=8)
    otp: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=128)


class ResetPasswordResponse(BaseModel):
    message: str = "Password updated. You can sign in with your new password."
