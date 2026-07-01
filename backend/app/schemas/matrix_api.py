"""Document matrix list query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class MatrixListRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=500)
    status: str | None = None
    route_target: str | None = Field(None, description="Filter by rule book route target")
    evaluation_status: str | None = Field(None, description="Filter by evaluation status")
