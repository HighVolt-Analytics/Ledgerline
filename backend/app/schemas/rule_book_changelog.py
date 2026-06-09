"""Rule book governance changelog schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RuleBookChangelogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event: str
    created_at: datetime
    detail: dict[str, Any] | None
