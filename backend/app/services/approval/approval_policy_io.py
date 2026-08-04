"""Org-scoped approval policy JSON store."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import uuid
from typing import Any

from app.config import get_settings
from app.schemas.approval_policy import ApprovalPolicyPayload, PolicyRule
from app.services.tenant.tenant_storage_paths import tenant_local_dir
from app.tenant_roles import APPROVAL_ACTIONS, APPROVAL_ROLES

_DEFAULT_RULES: list[dict[str, str]] = [
    {"id": "ap1", "condition": "Invoices > 5,000", "approver": "CFO approval"},
    {"id": "ap2", "condition": "Marketing Expense invoices", "approver": "Marketing Lead"},
    {"id": "ap3", "condition": "Suspense-routed invoices", "approver": "Finance Controller"},
    {"id": "ap4", "condition": "New vendor (first invoice)", "approver": "Bookkeeper review"},
]

_LEADERSHIP_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": True,
    "Approve": True,
    "Reject": True,
    "Post": True,
    "Edit Policy": False,
    "Manage Users": False,
}

_SUPERVISOR_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": True,
    "Approve": True,
    "Reject": True,
    "Post": False,
    "Edit Policy": False,
    "Manage Users": False,
}

_READ_COMMENT_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": True,
    "Approve": False,
    "Reject": False,
    "Post": False,
    "Edit Policy": False,
    "Manage Users": False,
}

_VIEW_ONLY_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": False,
    "Approve": False,
    "Reject": False,
    "Post": False,
    "Edit Policy": False,
    "Manage Users": False,
}

_DEFAULT_MATRIX: dict[str, dict[str, bool]] = {
    "Admin": {action: True for action in APPROVAL_ACTIONS},
    "Functional manager": dict(_LEADERSHIP_PERMS),
    "Functional supervisor": dict(_SUPERVISOR_PERMS),
    "Finance head": dict(_LEADERSHIP_PERMS),
    "Bookkeeper": dict(_READ_COMMENT_PERMS),
    "Auditor": dict(_READ_COMMENT_PERMS),
    "User": dict(_VIEW_ONLY_PERMS),
}

# Legacy matrix row labels → current labels
_LEGACY_MATRIX_ROWS: dict[str, str] = {
    "Approver": "Functional manager",
    "Viewer": "User",
}


def _legacy_policy_path() -> Path:
    return Path(get_settings().upload_dir) / "approval_policy.json"


def _policy_path(tenant_id: uuid.UUID | int) -> Path:
    return tenant_local_dir(tenant_id) / "approval_policy.json"


def _normalize_role_row(perms: dict[str, Any]) -> dict[str, bool]:
    """Normalize a single role row (Publish → Post, coerce bools)."""
    row = dict(perms)
    if "Publish" in row:
        if "Post" not in row:
            row["Post"] = row["Publish"]
        del row["Publish"]
    return {str(k): bool(v) for k, v in row.items()}


def _normalize_policy_matrix(matrix: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Map legacy roles/actions and ensure all current matrix rows exist."""
    remapped: dict[str, dict[str, bool]] = {}
    for role, perms in (matrix or {}).items():
        if not isinstance(perms, dict):
            continue
        label = _LEGACY_MATRIX_ROWS.get(str(role), str(role))
        remapped[label] = _normalize_role_row(perms)

    out: dict[str, dict[str, bool]] = {}
    for role in APPROVAL_ROLES:
        base = deepcopy(_DEFAULT_MATRIX[role])
        if role in remapped:
            base.update(remapped[role])
        out[role] = {action: bool(base.get(action, False)) for action in APPROVAL_ACTIONS}
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
    else:
        raw["matrix"] = deepcopy(_DEFAULT_MATRIX)
    return ApprovalPolicyPayload.model_validate(raw)


def save_policy_for_tenant(
    tenant_id: uuid.UUID | int, payload: ApprovalPolicyPayload
) -> ApprovalPolicyPayload:
    data = payload.model_dump()
    data["matrix"] = _normalize_policy_matrix(data.get("matrix") or {})
    _save_tenant_policy(tenant_id, data)
    return ApprovalPolicyPayload.model_validate(data)


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
