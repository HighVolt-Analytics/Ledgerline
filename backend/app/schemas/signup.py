"""Signup wizard API schemas."""

from pydantic import BaseModel, EmailStr, Field


class SignupRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(default="", max_length=255)


class SignupVerifyOtpRequest(BaseModel):
    otp: str = Field(min_length=4, max_length=8)


class SignupOrganizationRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    industry: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)


class SignupSelectPlanRequest(BaseModel):
    plan: str = Field(pattern=r"^(free|studio)$")


class SignupCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class SignupCompleteResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    redirect_to: str
    user: dict


class SignupSessionInfo(BaseModel):
    email: str
    full_name: str
    provider: str
    status: str
    organization_name: str | None = None
    country: str | None = None
    currency: str | None = None
    industry: str | None = None
    phone: str | None = None
    plan: str | None = None
    identity_via_oauth: bool = False


class SignupPlanOption(BaseModel):
    plan: str
    label: str
    monthly_credits: int
    max_users: int
    monthly_price: float
    currency_code: str
    social_integration: bool
    email_integration: bool


class SignupLinkResponse(BaseModel):
    path: str
    url: str
    aliases: list[str]
    embed_html: str


class OAuthProvidersResponse(BaseModel):
    google: bool
    microsoft: bool
    microsoft_public_client: bool


class OAuthFlowResult(BaseModel):
    result: str
    access_token: str | None = None
    refresh_token: str | None = None
    signup_token: str | None = None
    tenant_select_token: str | None = None
    accounts: list[dict] | None = None
    error: str | None = None


class MicrosoftPrepareResponse(BaseModel):
    authorize_url: str
    pkce_verifier: str
    client_id: str
    redirect_uri: str
    token_url: str


class MicrosoftCompleteRequest(BaseModel):
    state: str
    id_token: str
    access_token: str | None = None
