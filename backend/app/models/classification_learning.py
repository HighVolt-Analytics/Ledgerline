"""LLM classification learning loop and OCR cache (tenant RLS)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_JsonColumn = JSON().with_variant(JSONB, "postgresql")


class InvoiceOcrArtifact(Base):
    __tablename__ = "invoice_ocr_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    di_model: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(_JsonColumn, nullable=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ClassificationLearningEvent(Base):
    __tablename__ = "classification_learning_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ocr_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("invoice_ocr_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_suggested_dt: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    policy_winner_dt: Mapped[str | None] = mapped_column(String(16), nullable=True)
    human_confirmed_dt: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vendor_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    review_reasons: Mapped[list[Any] | None] = mapped_column(_JsonColumn, nullable=True)
    llm_response: Mapped[dict[str, Any] | None] = mapped_column(_JsonColumn, nullable=True)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
