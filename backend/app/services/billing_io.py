"""Org-scoped billing credits JSON store (no Stripe integration yet)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
import uuid

from app.config import get_settings
from app.schemas.billing import BillingStateResponse, CreditPack
from app.services.tenant_storage_paths import tenant_local_dir

CREDIT_PACKS: list[CreditPack] = [
    CreditPack(id="starter", name="Starter", credits=500, price_aud=49),
    CreditPack(id="team", name="Team", credits=2500, price_aud=199, popular=True),
    CreditPack(id="growth", name="Growth", credits=10000, price_aud=699),
    CreditPack(id="scale", name="Scale", credits=50000, price_aud=2999),
]

_DEFAULT_STATE: dict[str, Any] = {
    "balance": 500,
    "current_pack": "starter",
    "auto_recharge": False,
    "threshold": 100,
}


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


def _read_tenant_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "orgs" in data:
        return None
    return data if isinstance(data, dict) else None


def _save_tenant_state(tenant_id: uuid.UUID | int, state: dict[str, Any]) -> None:
    path = _billing_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def _migrate_from_legacy(tenant_id: uuid.UUID | int) -> dict[str, Any]:
    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(tenant_id))
    if raw is None:
        return deepcopy(_DEFAULT_STATE)
    state = {
        "balance": int(raw.get("balance", _DEFAULT_STATE["balance"])),
        "current_pack": str(raw.get("current_pack", _DEFAULT_STATE["current_pack"])),
        "auto_recharge": bool(raw.get("auto_recharge", _DEFAULT_STATE["auto_recharge"])),
        "threshold": int(raw.get("threshold", _DEFAULT_STATE["threshold"])),
    }
    _save_tenant_state(tenant_id, state)
    return state


def load_billing_for_tenant(tenant_id: uuid.UUID | int) -> BillingStateResponse:
    path = _billing_path(tenant_id)
    raw = _read_tenant_state(path)
    if raw is None:
        raw = _migrate_from_legacy(tenant_id)
    return BillingStateResponse(
        balance=int(raw.get("balance", _DEFAULT_STATE["balance"])),
        current_pack=str(raw.get("current_pack", _DEFAULT_STATE["current_pack"])),
        auto_recharge=bool(raw.get("auto_recharge", _DEFAULT_STATE["auto_recharge"])),
        threshold=int(raw.get("threshold", _DEFAULT_STATE["threshold"])),
        packs=CREDIT_PACKS,
    )


def save_billing_for_tenant(
    tenant_id: uuid.UUID | int, state: BillingStateResponse
) -> BillingStateResponse:
    _save_tenant_state(
        tenant_id,
        {
            "balance": state.balance,
            "current_pack": state.current_pack,
            "auto_recharge": state.auto_recharge,
            "threshold": state.threshold,
        },
    )
    return state


def purchase_pack(tenant_id: uuid.UUID | int, pack_id: str) -> BillingStateResponse:
    pack = next((p for p in CREDIT_PACKS if p.id == pack_id), None)
    if pack is None:
        raise ValueError("Unknown credit pack")
    state = load_billing_for_tenant(tenant_id)
    state.balance += pack.credits
    state.current_pack = pack.id
    return save_billing_for_tenant(tenant_id, state)


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
