"""Tenant API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    currency: str = "AUD"
    is_current: bool = False
