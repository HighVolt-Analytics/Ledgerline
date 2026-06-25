"""Tenant-scoped storage path helpers."""

from pathlib import Path

import pytest

from app.services.tenant_storage_paths import (
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


def test_billing_lazy_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.config import get_settings
    from app.services.billing_io import load_billing_for_tenant

    get_settings.cache_clear()
    legacy = tmp_path / "billing.json"
    legacy.write_text(
        '{"orgs": {"'
        + str(TESTING_TENANT_UUID)
        + '": {"balance": 99, "current_pack": "team", "auto_recharge": false, "threshold": 10}}}\n',
        encoding="utf-8",
    )
    state = load_billing_for_tenant(TESTING_TENANT_UUID)
    assert state.balance == 99
    per_tenant = tmp_path / "tenants" / str(TESTING_TENANT_UUID) / "billing.json"
    assert per_tenant.is_file()
    get_settings.cache_clear()
