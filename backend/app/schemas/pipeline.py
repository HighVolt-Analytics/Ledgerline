from typing import Literal

from pydantic import BaseModel

from app.schemas.invoice import InvoiceResponse

StageState = Literal["done", "pending", "fail", "skipped"]


class MatrixStageCell(BaseModel):
    stage: str
    state: StageState


class MatrixRowResponse(BaseModel):
    invoice: InvoiceResponse
    stages: list[MatrixStageCell]


class PipelineStepsResponse(BaseModel):
    steps: list[dict]
