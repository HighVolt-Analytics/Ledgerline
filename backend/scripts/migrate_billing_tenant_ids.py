"""Migrate billing.json org keys from legacy integer tenant ids to UUIDs."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID

_LEGACY_MAP = {
    "1": str(TESTING_TENANT_UUID),
    "2": str(PLATFORM_TENANT_UUID),
}


def migrate_billing_json() -> None:
    path = Path(get_settings().upload_dir) / "billing.json"
    if not path.is_file():
        print("No billing.json found — nothing to migrate.")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    orgs = data.get("orgs") or {}
    migrated = 0
    for legacy, uuid_key in _LEGACY_MAP.items():
        if legacy in orgs and uuid_key not in orgs:
            orgs[uuid_key] = orgs.pop(legacy)
            migrated += 1
    if migrated:
        data["orgs"] = orgs
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"Migrated {migrated} billing org key(s) in {path}")
    else:
        print("billing.json already uses UUID keys or has no legacy entries.")


if __name__ == "__main__":
    migrate_billing_json()
