"""Org-scoped approval policy JSON store."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import uuid
from typing import Any

from app.config import get_settings
from app.schemas.approval_policy import ApprovalPolicyPayload, PolicyRule
from app.services.tenant_storage_paths import tenant_local_dir

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
        "Post": True,
        "Edit Policy": True,
        "Manage Users": True,
    },
    "Approver": {
        "View": True,
        "Comment": True,
        "Approve": True,
        "Reject": True,
        "Post": True,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Bookkeeper": {
        "View": True,
        "Comment": True,
        "Approve": False,
        "Reject": False,
        "Post": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Viewer": {
        "View": True,
        "Comment": False,
        "Approve": False,
        "Reject": False,
        "Post": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
    "Auditor": {
        "View": True,
        "Comment": True,
        "Approve": False,
        "Reject": False,
        "Post": False,
        "Edit Policy": False,
        "Manage Users": False,
    },
}


def _legacy_policy_path() -> Path:
    return Path(get_settings().upload_dir) / "approval_policy.json"


def _policy_path(tenant_id: uuid.UUID | int) -> Path:
    return tenant_local_dir(tenant_id) / "approval_policy.json"


def _normalize_policy_matrix(matrix: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Map legacy Publish privilege to Post."""
    out: dict[str, dict[str, bool]] = {}
    for role, perms in (matrix or {}).items():
        if not isinstance(perms, dict):
            continue
        row = dict(perms)
        if "Publish" in row:
            if "Post" not in row:
                row["Post"] = row["Publish"]
            del row["Publish"]
        out[str(role)] = row
    return out


def default_policy_dict() -> dict[str, Any]:
    return {
        "locked": False,
        "rules": deepcopy(_DEFAULT_RULES),
        "matrix": deepcopy(_DEFAULT_MATRIX),
    }


def _load_legacy_store() -> dict[str, Any]:
    path = _legacy_policy_path()
    if not path.is_file():
        return {"orgs": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _read_tenant_policy(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "orgs" in data:
        return None
    return data if isinstance(data, dict) else None


def _save_tenant_policy(tenant_id: uuid.UUID | int, payload: dict[str, Any]) -> None:
    path = _policy_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def _migrate_from_legacy(tenant_id: uuid.UUID | int) -> dict[str, Any]:
    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(tenant_id)) or default_policy_dict()
    _save_tenant_policy(tenant_id, raw)
    return raw


def load_policy_for_tenant(tenant_id: uuid.UUID | int) -> ApprovalPolicyPayload:
    path = _policy_path(tenant_id)
    raw = _read_tenant_policy(path)
    if raw is None:
        raw = _migrate_from_legacy(tenant_id)
    if isinstance(raw.get("matrix"), dict):
        raw["matrix"] = _normalize_policy_matrix(raw["matrix"])
    return ApprovalPolicyPayload.model_validate(raw)


def save_policy_for_tenant(
    tenant_id: uuid.UUID | int, payload: ApprovalPolicyPayload
) -> ApprovalPolicyPayload:
    _save_tenant_policy(tenant_id, payload.model_dump())
    return payload


def unlock_policy(tenant_id: uuid.UUID | int, code: str) -> ApprovalPolicyPayload:
    settings = get_settings()
    expected = settings.approval_policy_unlock_code.strip()
    if code != expected:
        raise ValueError("Invalid unlock code")
    policy = load_policy_for_tenant(tenant_id)
    policy.locked = False
    return save_policy_for_tenant(tenant_id, policy)


def remove_policy_for_tenant(tenant_id: uuid.UUID | int) -> None:
    path = _policy_path(tenant_id)
    if path.is_file():
        path.unlink()

    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    key = str(tenant_id)
    if key in orgs:
        del orgs[key]
        store["orgs"] = orgs
        legacy = _legacy_policy_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        with legacy.open("w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
            fh.write("\n")


def validate_policy_payload(raw: dict[str, Any]) -> ApprovalPolicyPayload:
    rules = [PolicyRule.model_validate(r) for r in raw.get("rules") or []]
    matrix = _normalize_policy_matrix(raw.get("matrix") or _DEFAULT_MATRIX)
    return ApprovalPolicyPayload(
        locked=bool(raw.get("locked", False)),
        rules=rules,
        matrix=matrix,
    )
