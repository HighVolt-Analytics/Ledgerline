"""OCR extraction artifact from Azure Document Intelligence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OcrArtifact(BaseModel):
    success: bool = False
    sparse: bool = False
    text: str = ""
    text_length: int = 0
    di_model: str = ""
    layout_kv: dict[str, str] = Field(default_factory=dict)
    payload_json: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
