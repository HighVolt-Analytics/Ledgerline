"""Approval API query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class ApprovalListRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
