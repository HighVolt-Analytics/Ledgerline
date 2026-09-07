"""Slack workspace bot connection per tenant."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"
STATUS_ACTION_REQUIRED = "action_required"


class ConnectedSlackAccount(Base):
    __tablename__ = "connected_slack_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "team_id", name="uq_slack_tenant_team_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    team_id: Mapped[str] = mapped_column(String(64), index=True)
    team_name: Mapped[str | None] = mapped_column(String(256))
    bot_user_id: Mapped[str | None] = mapped_column(String(64))
    app_id: Mapped[str | None] = mapped_column(String(64))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String(32), default=STATUS_CONNECTED)
    integration_health: Mapped[str] = mapped_column(String(32), default=STATUS_CONNECTED)
    connected_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def is_connected(self) -> bool:
        return (
            self.connection_status == STATUS_CONNECTED
            and bool(self.access_token_encrypted)
        )
