"""Tenant-scoped approval policy store (Postgres source of truth).

Legacy filesystem JSON under ``UPLOAD_DIR/tenants/{id}/approval_policy.json`` is
migrated into the DB on first read. Sync helpers keep a short TTL cache and an
optional file mirror so unit tests / local tools keep working without a live DB.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import time
from copy import deepcopy
from pathlib import Path
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.approval_policy import ApprovalPolicyPayload, AmountApprovalTierRow
from app.services.approval.amount_tier_approval import (
    DEFAULT_AMOUNT_APPROVAL_TIERS,
    normalize_amount_approval_tiers,
)
from app.services.approval.approval_policy_repository import (
    delete_policy,
    fetch_policy_dict,
    upsert_policy,
)
from app.services.tenant.tenant_storage_paths import tenant_local_dir
from app.tenant_ids import parse_tenant_id
from app.tenant_roles import APPROVAL_ACTIONS, APPROVAL_ROLES
from app.utils.logger import get_logger

logger = get_logger(__name__)

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

_POLICY_CACHE: dict[uuid.UUID, tuple[float, ApprovalPolicyPayload]] = {}
_POLICY_CACHE_TTL_SEC = 30.0


def _db_bridge_enabled() -> bool:
    """When false (tests), sync IO uses filesystem only; API still uses the request DB."""
    return os.getenv("APPROVAL_POLICY_USE_DB", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
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


def _read_tenant_policy_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "orgs" in data:
        return None
    return data if isinstance(data, dict) else None


def _cleaned_policy_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "locked": bool(payload.get("locked", False)),
        "matrix": payload.get("matrix") or {},
        "approval_limits": payload.get("approval_limits") or {},
        "amount_approval_tiers": payload.get("amount_approval_tiers")
        or deepcopy(DEFAULT_AMOUNT_APPROVAL_TIERS),
    }


def _save_tenant_policy_file(tenant_id: uuid.UUID | int, payload: dict[str, Any]) -> None:
    path = _policy_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _cleaned_policy_dict(payload)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, indent=2)
        fh.write("\n")


def _read_legacy_org_policy(tenant_id: uuid.UUID | int) -> dict[str, Any] | None:
    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    raw = orgs.get(str(tenant_id))
    return raw if isinstance(raw, dict) else None


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


def _coerce_tenant_uuid(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    tid = parse_tenant_id(tenant_id)
    if tid is None:
        raise ValueError(f"Invalid tenant_id: {tenant_id!r}")
    return tid


def clear_approval_policy_cache(tenant_id: uuid.UUID | int | None = None) -> None:
    if tenant_id is None:
        _POLICY_CACHE.clear()
        return
    tid = parse_tenant_id(tenant_id)
    if tid is not None:
        _POLICY_CACHE.pop(tid, None)


def _cache_get(tenant_id: uuid.UUID) -> ApprovalPolicyPayload | None:
    hit = _POLICY_CACHE.get(tenant_id)
    if hit is None:
        return None
    expires_at, payload = hit
    if time.monotonic() > expires_at:
        _POLICY_CACHE.pop(tenant_id, None)
        return None
    return payload.model_copy(deep=True)


def _cache_set(tenant_id: uuid.UUID, payload: ApprovalPolicyPayload) -> None:
    _POLICY_CACHE[tenant_id] = (
        time.monotonic() + _POLICY_CACHE_TTL_SEC,
        payload.model_copy(deep=True),
    )


def _payload_from_raw(raw: dict[str, Any]) -> ApprovalPolicyPayload:
    return ApprovalPolicyPayload.model_validate(_normalize_raw_policy(raw))


def _run_coro_sync(coro: Any) -> Any:
    """Run an async coroutine from sync code (including inside a running loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    def _runner() -> Any:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_runner).result(timeout=30)


async def _fetch_db_with_rls(tenant_id: uuid.UUID) -> dict[str, Any] | None:
    from app.database import db_session_with_rls

    async with db_session_with_rls(tenant_id) as session:
        return await fetch_policy_dict(session, tenant_id)


async def _upsert_db_with_rls(
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    *,
    updated_by_user_id: int | None = None,
) -> dict[str, Any]:
    from app.database import db_session_with_rls

    async with db_session_with_rls(tenant_id) as session:
        return await upsert_policy(
            session,
            tenant_id,
            config,
            updated_by_user_id=updated_by_user_id,
        )


async def _delete_db_platform(tenant_id: uuid.UUID) -> None:
    from app.database import platform_lookup_session

    async with platform_lookup_session() as session:
        await delete_policy(session, tenant_id)
        await session.commit()


def _policy_needs_schema_heal(raw: dict[str, Any] | None) -> bool:
    """True when persisted JSON is pre-matrix legacy or missing required sections."""
    if not isinstance(raw, dict):
        return True
    if "rules" in raw and "amount_approval_tiers" not in raw:
        return True
    tiers = raw.get("amount_approval_tiers")
    if not isinstance(tiers, list) or not tiers:
        return True
    if "approval_limits" not in raw:
        return True
    matrix = raw.get("matrix")
    if not isinstance(matrix, dict):
        return True
    for role in APPROVAL_ROLES:
        if role not in matrix:
            return True
    return False


def _filesystem_raw(tenant_id: uuid.UUID) -> dict[str, Any] | None:
    raw = _read_tenant_policy_file(_policy_path(tenant_id))
    if raw is not None:
        return raw
    return _read_legacy_org_policy(tenant_id)


async def load_policy_for_tenant_async(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> ApprovalPolicyPayload:
    """Load policy from the request DB session; migrate/heal legacy rows into matrix schema."""
    tid = _coerce_tenant_uuid(tenant_id)
    # Always hit DB on request paths so multi-pod caches cannot serve a stale matrix.
    stored = await fetch_policy_dict(session, tid)
    if stored is None:
        file_raw = _filesystem_raw(tid)
        raw = file_raw if file_raw is not None else default_policy_dict()
        normalized = _normalize_raw_policy(raw)
        await upsert_policy(session, tid, normalized)
        payload = ApprovalPolicyPayload.model_validate(normalized)
    else:
        payload = _payload_from_raw(stored)
        if _policy_needs_schema_heal(stored):
            healed = payload.model_dump()
            await upsert_policy(session, tid, healed)
            logger.info(
                "approval_policy_schema_healed",
                tenant_id=str(tid),
                had_rules="rules" in stored,
                had_tiers=isinstance(stored.get("amount_approval_tiers"), list),
            )

    _cache_set(tid, payload)
    _save_tenant_policy_file(tid, payload.model_dump())
    return payload.model_copy(deep=True)


async def save_policy_for_tenant_async(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    payload: ApprovalPolicyPayload,
    *,
    updated_by_user_id: int | None = None,
) -> ApprovalPolicyPayload:
    tid = _coerce_tenant_uuid(tenant_id)
    data = payload.model_dump()
    data["matrix"] = _normalize_policy_matrix(data.get("matrix") or {})
    data["approval_limits"] = _normalize_approval_limits(data.get("approval_limits"))
    data["amount_approval_tiers"] = normalize_amount_approval_tiers(
        data.get("amount_approval_tiers")
    )
    await upsert_policy(
        session,
        tid,
        data,
        updated_by_user_id=updated_by_user_id,
    )
    saved = ApprovalPolicyPayload.model_validate(data)
    _cache_set(tid, saved)
    _save_tenant_policy_file(tid, data)
    return saved.model_copy(deep=True)


def load_policy_for_tenant(tenant_id: uuid.UUID | int | str) -> ApprovalPolicyPayload:
    tid = _coerce_tenant_uuid(tenant_id)
    cached = _cache_get(tid)
    if cached is not None:
        return cached

    raw: dict[str, Any] | None = None
    seeded_from_file = False
    if _db_bridge_enabled():
        try:
            raw = _run_coro_sync(_fetch_db_with_rls(tid))
        except Exception:
            logger.warning(
                "approval_policy_db_read_failed",
                tenant_id=str(tid),
                exc_info=True,
            )
            raw = None

    if raw is None:
        file_raw = _filesystem_raw(tid)
        if file_raw is not None:
            raw = file_raw
            seeded_from_file = True
        else:
            raw = default_policy_dict()
            seeded_from_file = True
    elif _policy_needs_schema_heal(raw):
        seeded_from_file = True  # force persist of healed modern schema

    payload = _payload_from_raw(raw)
    _cache_set(tid, payload)

    if _db_bridge_enabled() and seeded_from_file:
        try:
            _run_coro_sync(_upsert_db_with_rls(tid, payload.model_dump()))
        except Exception:
            logger.warning(
                "approval_policy_db_seed_failed",
                tenant_id=str(tid),
                exc_info=True,
            )
        _save_tenant_policy_file(tid, payload.model_dump())
    elif not _db_bridge_enabled():
        # Tests / local: keep filesystem materialization of defaults
        if not _policy_path(tid).is_file():
            _save_tenant_policy_file(tid, payload.model_dump())

    return payload.model_copy(deep=True)


def save_policy_for_tenant(
    tenant_id: uuid.UUID | int | str, payload: ApprovalPolicyPayload
) -> ApprovalPolicyPayload:
    tid = _coerce_tenant_uuid(tenant_id)
    data = payload.model_dump()
    data["matrix"] = _normalize_policy_matrix(data.get("matrix") or {})
    data["approval_limits"] = _normalize_approval_limits(data.get("approval_limits"))
    data["amount_approval_tiers"] = normalize_amount_approval_tiers(
        data.get("amount_approval_tiers")
    )
    saved = ApprovalPolicyPayload.model_validate(data)

    if _db_bridge_enabled():
        try:
            _run_coro_sync(_upsert_db_with_rls(tid, data))
        except Exception:
            logger.warning(
                "approval_policy_db_write_failed",
                tenant_id=str(tid),
                exc_info=True,
            )

    _save_tenant_policy_file(tid, data)
    _cache_set(tid, saved)
    return saved.model_copy(deep=True)


def unlock_policy(tenant_id: uuid.UUID | int | str, code: str) -> ApprovalPolicyPayload:
    settings = get_settings()
    expected = settings.approval_policy_unlock_code.strip()
    if code != expected:
        raise ValueError("Invalid unlock code")
    policy = load_policy_for_tenant(tenant_id)
    policy.locked = False
    return save_policy_for_tenant(tenant_id, policy)


async def unlock_policy_async(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    code: str,
    *,
    updated_by_user_id: int | None = None,
) -> ApprovalPolicyPayload:
    settings = get_settings()
    expected = settings.approval_policy_unlock_code.strip()
    if code != expected:
        raise ValueError("Invalid unlock code")
    policy = await load_policy_for_tenant_async(session, tenant_id)
    policy.locked = False
    return await save_policy_for_tenant_async(
        session,
        tenant_id,
        policy,
        updated_by_user_id=updated_by_user_id,
    )


def remove_policy_for_tenant(tenant_id: uuid.UUID | int | str) -> None:
    tid = _coerce_tenant_uuid(tenant_id)
    clear_approval_policy_cache(tid)

    path = _policy_path(tid)
    if path.is_file():
        path.unlink()

    store = _load_legacy_store()
    orgs = store.get("orgs") or {}
    key = str(tid)
    if key in orgs:
        del orgs[key]
        store["orgs"] = orgs
        legacy = _legacy_policy_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        with legacy.open("w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
            fh.write("\n")

    if _db_bridge_enabled():
        try:
            _run_coro_sync(_delete_db_platform(tid))
        except Exception:
            logger.warning(
                "approval_policy_db_delete_failed",
                tenant_id=str(tid),
                exc_info=True,
            )


def validate_policy_payload(raw: dict[str, Any]) -> ApprovalPolicyPayload:
    tiers = normalize_amount_approval_tiers(raw.get("amount_approval_tiers"))
    return ApprovalPolicyPayload(
        locked=bool(raw.get("locked", False)),
        matrix=_normalize_policy_matrix(raw.get("matrix") or _DEFAULT_MATRIX),
        approval_limits=_normalize_approval_limits(raw.get("approval_limits")),
        amount_approval_tiers=[AmountApprovalTierRow.model_validate(t) for t in tiers],
    )


# Back-compat aliases used by migration scripts
_save_tenant_policy = _save_tenant_policy_file
_read_tenant_policy = _read_tenant_policy_file


def _migrate_from_legacy(tenant_id: uuid.UUID | int) -> dict[str, Any]:
    """Legacy helper retained for scripts; prefer load_policy_for_tenant."""
    raw = _read_legacy_org_policy(tenant_id) or default_policy_dict()
    _save_tenant_policy_file(tenant_id, raw)
    return raw
