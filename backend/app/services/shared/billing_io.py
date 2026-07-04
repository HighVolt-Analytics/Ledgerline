"""Legacy per-tenant billing.json helpers (superseded by tenant_billing table)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

from app.config import get_settings
from app.services.tenant.tenant_storage_paths import tenant_local_dir


def _legacy_billing_path() -> Path:
    return Path(get_settings().upload_dir) / "billing.json"


def _billing_path(tenant_id: uuid.UUID | int) -> Path:
    return tenant_local_dir(tenant_id) / "billing.json"


def _load_legacy_store() -> dict[str, Any]:
    path = _legacy_billing_path()
    if not path.is_file():
        return {"orgs": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save_tenant_state(tenant_id: uuid.UUID | int, state: dict[str, Any]) -> None:
    path = _billing_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def remove_billing_for_tenant(tenant_id: uuid.UUID | int) -> None:
    path = _billing_path(tenant_id)
    if path.is_file():
        path.unlink()

    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    key = str(tenant_id)
    if key in orgs:
        del orgs[key]
        store["orgs"] = orgs
        legacy = _legacy_billing_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        with legacy.open("w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
            fh.write("\n")
