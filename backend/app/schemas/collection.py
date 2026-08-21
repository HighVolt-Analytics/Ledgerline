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


class CollectionMarkReceivedRequest(BaseModel):
    received_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
