from typing import Literal

from pydantic import BaseModel

from app.schemas.invoice import InvoiceResponse

StageState = Literal["done", "pending", "fail", "skipped"]


class MatrixStageCell(BaseModel):
    stage: str
    state: StageState
    when: str | None = None
    detail: str | None = None


class MatrixConflictRow(BaseModel):
    field: str
    this_doc: str
    other_doc: str


class MatrixRowResponse(BaseModel):
    invoice: InvoiceResponse
    stages: list[MatrixStageCell]
    flag: str = "Clean"
    flag_reason: str | None = None
    payment_status: str = "—"
    paid_date: str | None = None
    conflict_with: str | None = None
    conflict_detail: list[MatrixConflictRow] | None = None


class PipelineStepsResponse(BaseModel):
    steps: list[dict]
