"""API schema for the recognition signal registry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecognitionSignalCondition(BaseModel):
    field: str
    operator: str
    value: str


class RecognitionSignalEntry(BaseModel):
    id: str
    label: str
    hint: str
    channel: str
    strength: str
    example: str
    condition: RecognitionSignalCondition


class RecognitionSignalCatalogResponse(BaseModel):
    weak_signal_ids: list[str] = Field(default_factory=list)
    pick_groups: list[list[str]] = Field(default_factory=list)
    supporting_guards: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[RecognitionSignalEntry] = Field(default_factory=list)
    playbook_recommended_identity: dict[str, list[str]] = Field(default_factory=dict)
