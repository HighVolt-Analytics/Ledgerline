"""Audit log API request and response models."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    correlation_id: str | None
    event: str
    invoice_id: int | None
    detail: dict[str, object] | None
    created_at: datetime


class AuditLogListRequest(BaseModel):
    """Query parameters for paginated audit log listing."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)
    invoice_id: int | None = None
    event: str | None = None


class AuditLogExportRequest(BaseModel):
    """Query parameters for audit log CSV export."""

    model_config = ConfigDict(frozen=True)

    month: str | None = Field(
        None,
        description="Period as YYYY-MM (same as Reports analytics)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    )
    date_from: date | None = Field(None, description="Inclusive start (created_at)")
    date_to: date | None = Field(None, description="Inclusive end (created_at)")
    document_only: bool = Field(
        True,
        description=(
            "Exclude config noise (rule_book_updated, invoices_remapped) "
            "and rows without invoice_id"
        ),
    )
    dedupe: bool = Field(
        True,
        description="Keep only the latest row per invoice+event for high-churn lifecycle echoes",
    )
