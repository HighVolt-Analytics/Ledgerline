"""Platform super-admin API schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PlatformTenantModule(BaseModel):
    module_key: str
    is_active: bool


class PlatformTenantSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    lifecycle_status: str
    created_at: datetime | None = None
    user_count: int = 0
    invoice_count: int = 0
    credit_balance: int = 0


class PlatformTenantDetail(PlatformTenantSummary):
    settings_json: dict[str, Any] | None = None
    modules: list[PlatformTenantModule] = Field(default_factory=list)


class CreatePlatformTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class UpdatePlatformTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    lifecycle_status: str | None = Field(default=None, pattern=r"^(active|suspended|trial)$")
    settings_json: dict[str, Any] | None = None
    modules: list[PlatformTenantModule] | None = None
