"""Tenant member API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TenantMemberResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: str
    status: str
    is_active: bool


class PendingInviteResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    expires_at: datetime
    created_at: datetime


class TenantMembersListResponse(BaseModel):
    members: list[TenantMemberResponse]
    pending_invites: list[PendingInviteResponse]


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=32)


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class InviteMemberResponse(BaseModel):
    invite_id: int
    email: str
    accept_url: str
    expires_at: datetime
    email_sent: bool = False
    email_error: str | None = None
    already_member: bool = False


class InvitePreviewResponse(BaseModel):
    email: str
    full_name: str
    role: str
    tenant_name: str
    tenant_slug: str
    expired: bool
    accepted: bool


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=16)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class InviteAcceptResponse(BaseModel):
    message: str
    tenant_id: UUID
    tenant_name: str
    email: str


class PermissionsResponse(BaseModel):
    role: str
    matrix_role: str
    permissions: dict[str, bool]
    enabled_modules: dict[str, bool] = Field(default_factory=dict)
    can_reveal_bank: bool = False
