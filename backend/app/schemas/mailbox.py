"""Connected mailbox schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class MailboxCreate(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=255)


class MailboxResponse(BaseModel):
    id: int
    org_id: int
    email: str
    display_name: str | None
    is_active: bool
    last_poll_at: datetime | None

    model_config = {"from_attributes": True}
