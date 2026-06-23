"""WhatsApp Business Cloud API connection per org phone number."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"
STATUS_ACTION_REQUIRED = "action_required"


class ConnectedWhatsapp(Base):
    __tablename__ = "connected_whatsapp_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number_id", name="uq_whatsapp_tenant_phone_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    phone_number_id: Mapped[str] = mapped_column(String(64), index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    display_name: Mapped[str | None] = mapped_column(String(256))
    whatsapp_business_account_id: Mapped[str | None] = mapped_column(String(64), index=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
