"""Pydantic schemas for Viber integration APIs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ViberConnectionResponse(BaseModel):
    id: int
    tenant_id: UUID
    bot_id: str
    connection_status: str
    integration_health: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ViberStatusResponse(BaseModel):
    configured: bool
    webhook_callback_url: str
    webhook_reachable: bool
    webhook_reachability_hint: str | None = None
    connections: list[ViberConnectionResponse]


class ViberConnectBody(BaseModel):
    auth_token: str = Field(min_length=8, max_length=512)


class ViberConnectResponse(BaseModel):
    connection: ViberConnectionResponse
    bot_name: str | None = None


class ViberTestResponse(BaseModel):
    ok: bool
    integration_health: str
    warnings: list[str]
    profile: dict
