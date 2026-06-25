"""Tenant-scoped storage path helpers (local disk + Azure blob names)."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.config import get_settings

TENANTS_ROOT = "tenants"
_LEGACY_ROOTS = frozenset({"invoice", "rejected", "reports"})


def parse_tenant_id_value(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    return uuid.UUID(str(tenant_id))


def tenant_root(tenant_id: uuid.UUID | int | str) -> str:
    tid = parse_tenant_id_value(tenant_id)
    return f"{TENANTS_ROOT}/{tid}"


def tenant_blob_name(tenant_id: uuid.UUID | int | str, relative_path: str) -> str:
    rel = relative_path.strip().lstrip("/").replace("\\", "/")
    return f"{tenant_root(tenant_id)}/{rel}"


def tenant_local_dir(tenant_id: uuid.UUID | int | str, *parts: str) -> Path:
    base = Path(get_settings().upload_dir) / tenant_root(tenant_id)
    return base.joinpath(*parts) if parts else base


def blob_name_from_stored(stored: str | None) -> str | None:
    """Extract blob-relative path from azureblob:// URI or local uploads path."""
    if not stored or not stored.strip():
        return None
    from app.services import blob_storage

    parsed = blob_storage.parse_stored_uri(stored.strip())
    if parsed:
        return parsed[1]
    path = stored.strip().replace("\\", "/")
    upload_root = Path(get_settings().upload_dir).as_posix().rstrip("/")
    if path.startswith(upload_root + "/"):
        return path[len(upload_root) + 1 :]
    marker = f"/{TENANTS_ROOT}/"
    idx = path.find(marker)
    if idx >= 0:
        return path[idx + 1 :]
    for root in _LEGACY_ROOTS:
        pos = path.find(f"/{root}/")
        if pos >= 0:
            return path[pos + 1 :]
        if path.startswith(f"{root}/"):
            return path
    return None


def is_legacy_blob_path(name: str | None) -> bool:
    if not name:
        return False
    normalized = name.strip().lstrip("/").replace("\\", "/")
    if normalized.startswith(f"{TENANTS_ROOT}/"):
        return False
    root = normalized.split("/", 1)[0]
    return root in _LEGACY_ROOTS


def legacy_to_tenant_path(tenant_id: uuid.UUID | int | str, legacy_name: str) -> str:
    rel = legacy_name.strip().lstrip("/").replace("\\", "/")
    if rel.startswith(f"{TENANTS_ROOT}/"):
        return rel
    return tenant_blob_name(tenant_id, rel)


def _path_name_variants(name: str) -> list[str]:
    """Alternate blob paths (vendor punctuation, document-type folder encoding)."""
    variants = [name]
    parts = name.split("/")
    for idx, part in enumerate(parts):
        if not part.endswith("."):
            continue
        alt_parts = parts.copy()
        alt_parts[idx] = part[:-1]
        variants.append("/".join(alt_parts))

    for sep in ("\u00b7", "\ufffd"):
        if sep in name:
            variants.append(name.replace(sep, " - "))
            collapsed = name.replace(sep, " - ").replace("  ", " ")
            if collapsed != name.replace(sep, " - "):
                variants.append(collapsed)
            variants.append(name.replace(sep, "\u00b7 "))
            variants.append(name.replace(sep, "\u00b7"))
    if " - " in name:
        variants.append(name.replace(" - ", "\u00b7 "))
        variants.append(name.replace(" - ", "\u00b7"))

    seen: set[str] = set()
    unique: list[str] = []
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            unique.append(variant)
    return unique


def resolve_blob_candidates(
    stored: str | None,
    tenant_id: uuid.UUID | int | str | None = None,
    *,
    tenant_slug: str | None = None,
    tenant_name: str | None = None,
) -> list[str]:
    """Paths to try when reading a stored file (new layout, then legacy)."""
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name:
            return
        norm = name.strip().lstrip("/").replace("\\", "/")
        if norm and norm not in seen:
            seen.add(norm)
            names.append(norm)

    add(blob_name_from_stored(stored))
    if tenant_id is not None:
        for name in list(names):
            if is_legacy_blob_path(name):
                add(legacy_to_tenant_path(tenant_id, name))
    for name in list(names):
        for variant in _path_name_variants(name):
            add(variant)
    from app.services.vault_paths import (
        insert_org_segment_into_blob_path,
        strip_org_segment_from_blob_path,
        vault_tenant_folder,
    )

    for name in list(names):
        stripped = strip_org_segment_from_blob_path(name)
        add(stripped)
        if tenant_slug:
            org_folder = vault_tenant_folder(tenant_slug, tenant_name)
            add(insert_org_segment_into_blob_path(name, org_folder))
    return names
