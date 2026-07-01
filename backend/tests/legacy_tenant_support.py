"""Map legacy integer tenant ids (1, 2) to stable UUIDs in tests only."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID

_LEGACY_TENANT_MAP = {
    1: TESTING_TENANT_UUID,
    2: PLATFORM_TENANT_UUID,
}

_installed = False


def _coerce_legacy_tenant_ids(session: Session) -> None:
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Tenant):
            legacy_id = getattr(obj, "id", None)
            if isinstance(legacy_id, int) and legacy_id in _LEGACY_TENANT_MAP:
                obj.id = _LEGACY_TENANT_MAP[legacy_id]
        tenant_id = getattr(obj, "tenant_id", None)
        if isinstance(tenant_id, int) and tenant_id in _LEGACY_TENANT_MAP:
            obj.tenant_id = _LEGACY_TENANT_MAP[tenant_id]


def install_legacy_tenant_coercion() -> None:
    global _installed
    if _installed:
        return

    @event.listens_for(Session, "before_flush")
    def _on_before_flush(session, flush_context, instances) -> None:
        _coerce_legacy_tenant_ids(session)

    _installed = True
