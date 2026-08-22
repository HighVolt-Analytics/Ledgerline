"""Collections (AR) workflow schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CollectionResponse(BaseModel):
    id: int
    invoice_id: int
    customer: str | None = None
    amount: float
    currency: str = ""
    status: str
    tab: str
    due_date: date | None = None
    received_date: datetime | None = None
    failure_reason: str | None = None


class CollectionWorkspaceKpis(BaseModel):
    open_count: int = 0
    overdue_count: int = 0
    due_soon_count: int = 0
    queue_count: int = 0
    awaiting_count: int = 0
    received_count: int = 0
    failed_count: int = 0
    outstanding_by_currency: dict[str, float] = Field(default_factory=dict)


class CollectionMarkReceivedRequest(BaseModel):
    received_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
