"""Approval API query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class ApprovalListRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class EscalateApprovalRequest(BaseModel):
    """Note recorded when an approver escalates an item still in the queue."""

    note: str = Field(min_length=1, max_length=2000)
