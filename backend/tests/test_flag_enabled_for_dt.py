"""Per-DT feature flag tests."""

from __future__ import annotations

import pytest

from app.config import flag_enabled_for_dt, get_settings


def test_flag_off_globally() -> None:
    get_settings.cache_clear()
    assert flag_enabled_for_dt("use_field_fusion", "DT-01") is False


def test_flag_on_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("USE_CITATION_GROUNDING", "true")
    assert flag_enabled_for_dt("use_citation_grounding", "DT-13") is True
    get_settings.cache_clear()


def test_flag_on_with_allowlist_blocks_other_dt(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("USE_CITATION_GROUNDING", "true")
    monkeypatch.setenv(
        "EXTRACTION_FLAG_DT_ALLOWLISTS_JSON",
        '{"use_citation_grounding": ["DT-13"]}',
    )
    assert flag_enabled_for_dt("use_citation_grounding", "DT-13") is True
    assert flag_enabled_for_dt("use_citation_grounding", "DT-01") is False
    get_settings.cache_clear()
