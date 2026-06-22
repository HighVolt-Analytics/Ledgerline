"""Org-scoped billing credits JSON store (no Stripe integration yet)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.billing import BillingStateResponse, CreditPack

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


def _billing_path() -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / "billing.json"


def _load_store() -> dict[str, Any]:
    path = _billing_path()
    if not path.is_file():
        return {"orgs": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save_store(data: dict[str, Any]) -> None:
    path = _billing_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def load_billing_for_tenant(tenant_id: int) -> BillingStateResponse:
    store = _load_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(tenant_id)) or deepcopy(_DEFAULT_STATE)
    return BillingStateResponse(
        balance=int(raw.get("balance", _DEFAULT_STATE["balance"])),
        current_pack=str(raw.get("current_pack", _DEFAULT_STATE["current_pack"])),
        auto_recharge=bool(raw.get("auto_recharge", _DEFAULT_STATE["auto_recharge"])),
        threshold=int(raw.get("threshold", _DEFAULT_STATE["threshold"])),
        packs=CREDIT_PACKS,
    )


def save_billing_for_tenant(tenant_id: int, state: BillingStateResponse) -> BillingStateResponse:
    store = _load_store()
    orgs = store.setdefault("orgs", {})
    orgs[str(tenant_id)] = {
        "balance": state.balance,
        "current_pack": state.current_pack,
        "auto_recharge": state.auto_recharge,
        "threshold": state.threshold,
    }
    _save_store(store)
    return state


def purchase_pack(tenant_id: int, pack_id: str) -> BillingStateResponse:
    pack = next((p for p in CREDIT_PACKS if p.id == pack_id), None)
    if pack is None:
        raise ValueError("Unknown credit pack")
    state = load_billing_for_tenant(tenant_id)
    state.balance += pack.credits
    state.current_pack = pack.id
    return save_billing_for_tenant(tenant_id, state)
