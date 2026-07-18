"""Platform-wide LLM prompt versions (Developer Port)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformPromptVersion(Base):
    __tablename__ = "platform_prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_key", "version", name="uq_platform_prompt_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PlatformPromptActive(Base):
    __tablename__ = "platform_prompt_active"

    prompt_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    active_version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("platform_prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
