"""Upload / matrix analysis aggregates."""

from pydantic import BaseModel, ConfigDict, Field


class MatrixAnalysisBoardRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(description="review | processing | approved | rejected")
    column: str
    items: int = 0
    value_by_currency: dict[str, float] = Field(default_factory=dict)
    avg_wait_days: float = 0
    flagged: int = 0


class MatrixAnalysisFunnelRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    count: int = 0
    delta: int | None = None
    pct: float = 0


class MatrixAnalysisIssueRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    items: int = 0
    at_risk_by_currency: dict[str, float] = Field(default_factory=dict)
    severity: str = Field(description="High | Medium | Low")
    highlight: bool = False


class MatrixAnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_count: int = 0
    flagged: int = 0
    duplicates: int = 0
    awaiting: int = 0
    paid_this_month: int = 0
    truncated: bool = False
    analyzed_count: int = 0


class MatrixAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_board: list[MatrixAnalysisBoardRow]
    processing_funnel: list[MatrixAnalysisFunnelRow]
    exception_mix: list[MatrixAnalysisIssueRow]
    summary: MatrixAnalysisSummary
