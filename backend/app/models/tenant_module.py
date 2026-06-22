import uuid
"""Per-tenant feature entitlements."""

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TenantModule(Base):
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="uq_tenant_modules_tenant_key"),
    )
    __tablename__ = "tenant_modules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    module_key: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
