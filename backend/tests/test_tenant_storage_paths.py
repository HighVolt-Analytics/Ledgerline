"""Tenant-scoped storage path helpers."""

from pathlib import Path

import pytest

from app.services.tenant.tenant_storage_paths import (
    is_legacy_blob_path,
    legacy_to_tenant_path,
    resolve_blob_candidates,
    tenant_blob_name,
    tenant_root,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_tenant_root_and_blob_name() -> None:
    root = tenant_root(TESTING_TENANT_UUID)
    assert root == f"tenants/{TESTING_TENANT_UUID}"
    assert tenant_blob_name(TESTING_TENANT_UUID, "invoice/HvOrg/x.pdf") == (
        f"tenants/{TESTING_TENANT_UUID}/invoice/HvOrg/x.pdf"
    )


def test_legacy_detection_and_migration_path() -> None:
    legacy = "invoice/HvOrg/Unrouted/file.pdf"
    assert is_legacy_blob_path(legacy) is True
    migrated = legacy_to_tenant_path(TESTING_TENANT_UUID, legacy)
    assert migrated.startswith(f"tenants/{TESTING_TENANT_UUID}/invoice/")


def test_resolve_blob_candidates_includes_legacy_and_tenant() -> None:
    legacy = "invoice/HvOrg/a.pdf"
    names = resolve_blob_candidates(legacy, tenant_id=TESTING_TENANT_UUID)
    assert legacy in names
    assert legacy_to_tenant_path(TESTING_TENANT_UUID, legacy) in names


def test_resolve_blob_candidates_includes_document_type_folder_encoding_variants() -> None:
    stored = (
        f"tenants/{TESTING_TENANT_UUID}/invoice/Vault/DT-03 \ufffd Cargo Clearance Permit/x.pdf"
    )
    names = resolve_blob_candidates(stored, tenant_id=TESTING_TENANT_UUID)
    assert any("DT-03 - Cargo Clearance Permit" in name for name in names)
    assert any("DT-03 \u00b7 Cargo Clearance Permit" in name for name in names)


def test_billing_legacy_json_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.config import get_settings
    from app.services.shared.billing_io import _billing_path, remove_billing_for_tenant

    get_settings.cache_clear()
    per_tenant = _billing_path(TESTING_TENANT_UUID)
    per_tenant.parent.mkdir(parents=True, exist_ok=True)
    per_tenant.write_text('{"balance": 99}\n', encoding="utf-8")
    assert per_tenant.is_file()
    remove_billing_for_tenant(TESTING_TENANT_UUID)
    assert not per_tenant.is_file()
    get_settings.cache_clear()
