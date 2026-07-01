"""Viber Public Account connection per tenant bot."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"
STATUS_ACTION_REQUIRED = "action_required"


class ConnectedViberAccount(Base):
    __tablename__ = "connected_viber_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bot_id", name="uq_viber_tenant_bot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String(32), default=STATUS_CONNECTED)
    integration_health: Mapped[str] = mapped_column(String(32), default=STATUS_CONNECTED)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    @property
    def is_connected(self) -> bool:
        return (
            self.connection_status == STATUS_CONNECTED
            and bool(self.auth_token_encrypted)
        )
