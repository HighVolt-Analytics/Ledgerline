"""Query params for subledger balance endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SubledgerBalancesRequest(BaseModel):
    as_of: date | None = None
    include_unregistered: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
