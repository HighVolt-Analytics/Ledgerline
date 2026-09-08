"""Document matrix list query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class MatrixListRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    status: str | None = None
    route_target: str | None = Field(
        None, description="Comma-separated rule book route targets"
    )
    evaluation_status: str | None = Field(None, description="Filter by evaluation status")
    capture_source: str | None = Field(None, description="Filter by capture channel")
    q: str | None = Field(None, description="Search vendor, invoice no, PO, document ref")
    matrix_filter: str | None = Field(
        None,
        description=(
            "all | anomalies | awaiting | paid | pending | failed | "
            "duplicates | exclude_duplicates"
        ),
    )
    approval_board_column: str | None = Field(
        None,
        description="Comma-separated: review, processing, approved, rejected",
    )
