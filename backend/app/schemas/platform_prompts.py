"""Schemas for platform Developer Port prompt registry."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformPromptSummary(BaseModel):
    key: str
    label: str
    group: str
    description: str
    placeholders: list[str] = Field(default_factory=list)
    default_body: str
    body: str
    version: int | None = None
    is_overridden: bool = False
    updated_at: datetime | None = None
    notes: str | None = None


class PlatformPromptVersionCreate(BaseModel):
    body: str = Field(min_length=1)
    notes: str | None = None


class PlatformPromptVersionItem(BaseModel):
    version: int
    body: str
    notes: str | None = None
    created_at: datetime | None = None
    created_by_user_id: int | None = None
    is_active: bool = False


class PlatformPromptVersionListResponse(BaseModel):
    items: list[PlatformPromptVersionItem]
