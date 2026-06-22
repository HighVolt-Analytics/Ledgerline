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


class ApiEnvelope(BaseModel, Generic[T]):
    data: T | None = None
    error: ErrorDetail | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
