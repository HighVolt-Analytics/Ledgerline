"""Org-scoped approval policy JSON store (privilege matrix + limits)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import uuid
from typing import Any

from app.config import get_settings
from app.schemas.approval_policy import ApprovalPolicyPayload, AmountApprovalTierRow
from app.services.approval.amount_tier_approval import (
    DEFAULT_AMOUNT_APPROVAL_TIERS,
    normalize_amount_approval_tiers,
)
from app.services.tenant.tenant_storage_paths import tenant_local_dir
from app.tenant_roles import APPROVAL_ACTIONS, APPROVAL_ROLES

_LEADERSHIP_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": True,
    "Approve": True,
    "Edit Policy": False,
    "Manage Users": False,
}

_VIEW_ONLY_PERMS: dict[str, bool] = {
    "View": True,
    "Comment": False,
    "Approve": False,
    "Edit Policy": False,
    "Manage Users": False,
}

_DEFAULT_MATRIX: dict[str, dict[str, bool]] = {
    "Employee": dict(_VIEW_ONLY_PERMS),
    "Manager": dict(_LEADERSHIP_PERMS),
    "Department Head": dict(_LEADERSHIP_PERMS),
    "Finance Manager": dict(_LEADERSHIP_PERMS),
    "CFO": dict(_LEADERSHIP_PERMS),
    "Director": dict(_LEADERSHIP_PERMS),
    "Admin": {action: True for action in APPROVAL_ACTIONS},
}

_DEFAULT_APPROVAL_LIMITS: dict[str, float | None] = {role: None for role in APPROVAL_ROLES}

# Legacy matrix row labels → current labels
_LEGACY_MATRIX_ROWS: dict[str, str] = {
    "Approver": "Manager",
    "Viewer": "Employee",
    "User": "Employee",
    "Functional manager": "Manager",
    "Functional supervisor": "Department Head",
    "Finance head": "Finance Manager",
    "Bookkeeper": "CFO",
    "Auditor": "Director",
}


def _normalize_approval_limits(raw: Any) -> dict[str, float | None]:
    """Ensure every role has a limit entry; coerce numeric values; ignore unknown roles."""
    out: dict[str, float | None] = dict(_DEFAULT_APPROVAL_LIMITS)
    if not isinstance(raw, dict):
        return out
    for role_key, value in raw.items():
        label = _LEGACY_MATRIX_ROWS.get(str(role_key), str(role_key))
        if label not in APPROVAL_ROLES:
            continue
        if value is None or value == "":
            out[label] = None
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            out[label] = None
            continue
        if num != num or num < 0:  # NaN or negative
            out[label] = None
        else:
            out[label] = num
    return out


def _legacy_policy_path() -> Path:
    return Path(get_settings().upload_dir) / "approval_policy.json"


def _policy_path(tenant_id: uuid.UUID | int) -> Path:
    return tenant_local_dir(tenant_id) / "approval_policy.json"


def _normalize_role_row(perms: dict[str, Any]) -> dict[str, bool]:
    """Fold Reject/Post/Publish into Approve; keep only known action keys present."""
    row = {str(k): bool(v) for k, v in dict(perms).items()}
    had_approve_family = any(k in row for k in ("Approve", "Reject", "Post", "Publish"))
    can_approve = bool(
        row.pop("Approve", False)
        or row.pop("Reject", False)
        or row.pop("Post", False)
        or row.pop("Publish", False)
    )
    out: dict[str, bool] = {
        action: bool(row[action])
        for action in APPROVAL_ACTIONS
        if action != "Approve" and action in row
    }
    if had_approve_family:
        out["Approve"] = can_approve
    return out


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
        "matrix": deepcopy(_DEFAULT_MATRIX),
        "approval_limits": dict(_DEFAULT_APPROVAL_LIMITS),
        "amount_approval_tiers": deepcopy(DEFAULT_AMOUNT_APPROVAL_TIERS),
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
    cleaned = {
        "locked": bool(payload.get("locked", False)),
        "matrix": payload.get("matrix") or {},
        "approval_limits": payload.get("approval_limits") or {},
        "amount_approval_tiers": payload.get("amount_approval_tiers")
        or deepcopy(DEFAULT_AMOUNT_APPROVAL_TIERS),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, indent=2)
        fh.write("\n")


def _migrate_from_legacy(tenant_id: uuid.UUID | int) -> dict[str, Any]:
    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(tenant_id)) or default_policy_dict()
    _save_tenant_policy(tenant_id, raw)
    return raw


def _normalize_raw_policy(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "locked": bool(raw.get("locked", False)),
        "matrix": (
            _normalize_policy_matrix(raw["matrix"])
            if isinstance(raw.get("matrix"), dict)
            else deepcopy(_DEFAULT_MATRIX)
        ),
        "approval_limits": _normalize_approval_limits(raw.get("approval_limits")),
        "amount_approval_tiers": normalize_amount_approval_tiers(
            raw.get("amount_approval_tiers")
        ),
    }


def load_policy_for_tenant(tenant_id: uuid.UUID | int) -> ApprovalPolicyPayload:
    path = _policy_path(tenant_id)
    raw = _read_tenant_policy(path)
    if raw is None:
        raw = _migrate_from_legacy(tenant_id)
    raw = _normalize_raw_policy(raw)
    return ApprovalPolicyPayload.model_validate(raw)


def save_policy_for_tenant(
    tenant_id: uuid.UUID | int, payload: ApprovalPolicyPayload
) -> ApprovalPolicyPayload:
    data = payload.model_dump()
    data["matrix"] = _normalize_policy_matrix(data.get("matrix") or {})
    data["approval_limits"] = _normalize_approval_limits(data.get("approval_limits"))
    data["amount_approval_tiers"] = normalize_amount_approval_tiers(
        data.get("amount_approval_tiers")
    )
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
    tiers = normalize_amount_approval_tiers(raw.get("amount_approval_tiers"))
    return ApprovalPolicyPayload(
        locked=bool(raw.get("locked", False)),
        matrix=_normalize_policy_matrix(raw.get("matrix") or _DEFAULT_MATRIX),
        approval_limits=_normalize_approval_limits(raw.get("approval_limits")),
        amount_approval_tiers=[AmountApprovalTierRow.model_validate(t) for t in tiers],
    )
