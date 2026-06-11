"""Outlook mailbox connected for invoice ingestion."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

AUTH_APPLICATION = "application"
AUTH_DELEGATED = "delegated"

STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"


class ConnectedMailbox(Base):
    __tablename__ = "connected_mailboxes"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_mailbox_org_email"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_type: Mapped[str] = mapped_column(String(32), default=AUTH_APPLICATION)
    connection_status: Mapped[str] = mapped_column(String(32), default=STATUS_CONNECTED)
    oauth_user_id: Mapped[str | None] = mapped_column(String(128))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oauth_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    @property
    def is_oauth_connected(self) -> bool:
        return (
            self.auth_type == AUTH_DELEGATED
            and self.connection_status == STATUS_CONNECTED
            and bool(self.refresh_token_encrypted or self.access_token_encrypted)
        )

    @property
    def is_pollable(self) -> bool:
        if not self.is_active:
            return False
        if self.auth_type == AUTH_DELEGATED:
            return self.is_oauth_connected
        return self.connection_status == STATUS_CONNECTED
