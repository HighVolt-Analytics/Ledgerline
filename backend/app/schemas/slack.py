"""Pydantic schemas for Slack integration APIs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SlackConnectionResponse(BaseModel):
    id: int
    tenant_id: UUID
    team_id: str
    team_name: str | None
    bot_user_id: str | None
    app_id: str | None
    connection_status: str
    integration_health: str
    last_error: str | None
    last_sync_at: datetime | None
    connected_by_user_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SlackStatusResponse(BaseModel):
    configured: bool
    webhook_callback_url: str
    oauth_callback_url: str
    connections: list[SlackConnectionResponse]


class SlackAuthorizeResponse(BaseModel):
    authorize_url: str


class SlackTestResponse(BaseModel):
    ok: bool
    integration_health: str
    warnings: list[str]
    profile: dict
