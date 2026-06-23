"""Pydantic schemas for WhatsApp integration APIs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WhatsappConnectionResponse(BaseModel):
    id: int
    tenant_id: UUID
    phone_number_id: str
    phone_number: str | None
    display_name: str | None
    whatsapp_business_account_id: str | None
    connection_status: str
    integration_health: str
    last_error: str | None
    last_sync_at: datetime | None
    connected_by_user_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhatsappStatusResponse(BaseModel):
    configured: bool
    webhook_callback_url: str
    oauth_callback_url: str
    connections: list[WhatsappConnectionResponse]


class WhatsappAuthorizeResponse(BaseModel):
    authorize_url: str


class WhatsappTestResponse(BaseModel):
    ok: bool
    integration_health: str
    warnings: list[str]
    profile: dict
