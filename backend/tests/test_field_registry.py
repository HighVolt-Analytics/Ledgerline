"""Field registry loader and adapter tests."""

from __future__ import annotations

import os

import pytest

from app.registry.adapter import RegistryAdapter, get_registry_adapter
from app.registry.loader import clear_field_registry_cache, get_field_registry
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS


@pytest.fixture(autouse=True)
def _reset_registry_cache() -> None:
    clear_field_registry_cache()
    get_registry_adapter.cache_clear()
    yield
    clear_field_registry_cache()
    get_registry_adapter.cache_clear()


def test_field_registry_covers_all_canonical_keys() -> None:
    registry = get_field_registry()
    missing = CANONICAL_EXTRACTION_FIELD_KEYS - set(registry.fields.keys())
    assert not missing, f"missing registry entries: {sorted(missing)}"


def test_registry_adapter_legacy_posting_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_REGISTRY", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    adapter = RegistryAdapter()
    assert "total" in adapter.posting_critical_keys()
    assert "attachment_name" not in adapter.posting_critical_keys()


def test_registry_adapter_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_REGISTRY", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    adapter = RegistryAdapter()
    vendor = adapter.field_def("vendor")
    assert vendor is not None
    assert vendor.posting_critical is True
    assert vendor.label == "Vendor"
    assert adapter.hint_for("invoice_no")


def test_jurisdiction_variant_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_REGISTRY", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    adapter = RegistryAdapter()
    au = adapter.jurisdiction_variant("abn", "AU")
    assert au.name == "ABN"
    assert au.checksum == "abn_checksum"
    default = adapter.jurisdiction_variant("abn", "XX")
    assert default.name == "Tax ID"


def test_do_not_confuse_pairs_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_FIELD_REGISTRY", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    pairs = get_registry_adapter().do_not_confuse_pairs(["vendor", "invoice_no"])
    flat = {left for left, _ in pairs} | {right for _, right in pairs}
    assert "vendor" in flat or "invoice_no" in flat
