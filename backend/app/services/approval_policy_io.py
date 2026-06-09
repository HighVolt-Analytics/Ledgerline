"""Org-scoped approval policy JSON store."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.approval_policy import ApprovalPolicyPayload, PolicyRule

_DEFAULT_RULES: list[dict[str, str]] = [
    {"id": "ap1", "condition": "Invoices > 5,000", "approver": "CFO approval"},
    {"id": "ap2", "condition": "Marketing Expense invoices", "approver": "Marketing Lead"},
    {"id": "ap3", "condition": "Suspense-routed invoices", "approver": "Finance Controller"},
    {"id": "ap4", "condition": "New vendor (first invoice)", "approver": "Bookkeeper review"},
]

_DEFAULT_MATRIX: dict[str, dict[str, bool]] = {
    "Admin": {
        "View": True,
        "Comment": True,
        "Approve": True,
        "Reject": True,
        "Publish": True,
        "Edit Policy": True,
        "Manage Users": True,
    },
    "Approver": {
        "View": True,
        "Comment": True,
        "Approve": True,
        "Reject": True,
        "Publish": True,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Bookkeeper": {
        "View": True,
        "Comment": True,
        "Approve": False,
        "Reject": False,
        "Publish": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Viewer": {
        "View": True,
        "Comment": False,
        "Approve": False,
        "Reject": False,
        "Publish": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Auditor": {
        "View": True,
        "Comment": True,
        "Approve": False,
        "Reject": False,
        "Publish": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
}


def _policy_path() -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / "approval_policy.json"


def default_policy_dict() -> dict[str, Any]:
    return {
        "locked": False,
        "rules": deepcopy(_DEFAULT_RULES),
        "matrix": deepcopy(_DEFAULT_MATRIX),
    }


def _load_store() -> dict[str, Any]:
    path = _policy_path()
    if not path.is_file():
        return {"orgs": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save_store(data: dict[str, Any]) -> None:
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def load_policy_for_org(org_id: int) -> ApprovalPolicyPayload:
    store = _load_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(org_id)) or default_policy_dict()
    return ApprovalPolicyPayload.model_validate(raw)


def save_policy_for_org(org_id: int, payload: ApprovalPolicyPayload) -> ApprovalPolicyPayload:
    store = _load_store()
    orgs = store.setdefault("orgs", {})
    orgs[str(org_id)] = payload.model_dump()
    _save_store(store)
    return payload


def unlock_policy(org_id: int, code: str) -> ApprovalPolicyPayload:
    settings = get_settings()
    expected = settings.approval_policy_unlock_code.strip()
    if code != expected:
        raise ValueError("Invalid unlock code")
    policy = load_policy_for_org(org_id)
    policy.locked = False
    return save_policy_for_org(org_id, policy)


def validate_policy_payload(raw: dict[str, Any]) -> ApprovalPolicyPayload:
    rules = [PolicyRule.model_validate(r) for r in raw.get("rules") or []]
    return ApprovalPolicyPayload(
        locked=bool(raw.get("locked", False)),
        rules=rules,
        matrix=dict(raw.get("matrix") or _DEFAULT_MATRIX),
    )
