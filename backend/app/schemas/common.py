from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ResponseMeta(BaseModel):
    page: int = 1
    total: int = 0
    pages: int = 0
    segment_count: int | None = None
    segment_invoice_ids: list[int] | None = None
    # Approval quorum progress (approve endpoint)
    quorum_module: str | None = None
    quorum_mode: str | None = None
    quorum_required: int | None = None
    quorum_recorded: int | None = None
    quorum_remaining: int | None = None
    quorum_met: bool | None = None
    matrix_document_count: int | None = None
    matrix_flagged: int | None = None
    matrix_duplicates: int | None = None
    matrix_awaiting: int | None = None
    matrix_paid_this_month: int | None = None


class ApiEnvelope(BaseModel, Generic[T]):
    data: T | None = None
    error: ErrorDetail | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
