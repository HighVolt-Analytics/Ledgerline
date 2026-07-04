"""Split legacy billing.json org keys into per-tenant tenants/{uuid}/billing.json files."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings
from app.services.shared.billing_io import _billing_path, _legacy_billing_path, _save_tenant_state
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID

_LEGACY_MAP = {
    "1": str(TESTING_TENANT_UUID),
    "2": str(PLATFORM_TENANT_UUID),
}


def migrate_billing_json() -> None:
    legacy = _legacy_billing_path()
    if not legacy.is_file():
        print("No billing.json found — nothing to migrate.")
        return
    data = json.loads(legacy.read_text(encoding="utf-8"))
    orgs = data.get("orgs") or {}
    migrated = 0
    for key, state in list(orgs.items()):
        tid = _LEGACY_MAP.get(key, key)
        if _billing_path(tid).is_file():
            continue
        _save_tenant_state(
            tid,
            {
                "balance": int(state.get("balance", 500)),
                "current_pack": str(state.get("current_pack", "starter")),
                "auto_recharge": bool(state.get("auto_recharge", False)),
                "threshold": int(state.get("threshold", 100)),
            },
        )
        migrated += 1
        print(f"Migrated billing for tenant {tid}")
    if migrated:
        print(f"Split {migrated} tenant billing record(s) from {legacy}")
    else:
        print("billing.json already split or has no org entries.")


if __name__ == "__main__":
    migrate_billing_json()
