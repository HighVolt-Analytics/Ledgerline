"""Connected mailbox schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class MailboxCreate(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=255)


class MailboxConnectionRequestCreate(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=2000)


class MailboxConnectionRequestResponse(BaseModel):
    id: int
    org_id: int
    requested_email: str
    display_name: str | None
    message: str | None
    status: str
    invite_sent_at: datetime | None
    expires_at: datetime | None
    connected_at: datetime | None
    connected_mailbox_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MailboxConnectionRequestActionResponse(MailboxConnectionRequestResponse):
    connect_url: str
    email_sent: bool
    email_error: str | None = None


class MailboxInviteLinkResponse(BaseModel):
    connect_url: str


class MailboxInvitePreviewResponse(BaseModel):
    org_name: str
    requested_email: str
    display_name: str | None
    message: str | None
    expires_at: datetime | None


class MailboxAuthorizeResponse(BaseModel):
    authorize_url: str


class MailboxAdminConsentResponse(BaseModel):
    admin_consent_url: str
    instructions: str


class MailboxResponse(BaseModel):
    id: int
    org_id: int
    email: str
    display_name: str | None
    is_active: bool
    auth_type: str = "application"
    connection_status: str = "connected"
    oauth_connected_at: datetime | None = None
    last_error: str | None = None
    last_poll_at: datetime | None = None

    model_config = {"from_attributes": True}
