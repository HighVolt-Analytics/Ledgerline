"""Prevent duplicate Meta webhook message processing."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MetaWebhookDedupe(Base):
    __tablename__ = "meta_webhook_dedupe"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_mid: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
