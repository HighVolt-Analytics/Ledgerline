"""Auth request/response schemas."""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    org_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SwitchOrgRequest(BaseModel):
    org_id: int = Field(ge=1)


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    org_id: int
    org_name: str
    org_slug: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
