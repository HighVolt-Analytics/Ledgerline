"""Tests for GET /api/rule-book/recognition-signals."""

from app.services.recognition_signal_registry import (
    SIGNAL_CONDITIONS,
    SIGNAL_PICK_GROUPS,
    WEAK_SIGNAL_IDS,
    catalog_payload,
)


def test_catalog_payload_includes_extended_signal_groups() -> None:
    payload = catalog_payload()
    assert len(payload["pick_groups"]) == 23
    assert "text_recurring" in SIGNAL_CONDITIONS
    assert "channel_whatsapp" in SIGNAL_CONDITIONS
    assert payload["weak_signal_ids"] == sorted(WEAK_SIGNAL_IDS)
    signal_ids = {row["id"] for row in payload["signals"]}
    assert signal_ids == set(SIGNAL_CONDITIONS.keys())


def test_filename_and_text_patterns_aligned_with_conditions() -> None:
    from app.services.recognition_signal_registry import (
        filename_detection_patterns,
        text_detection_patterns,
    )

    for signal_id, pattern in filename_detection_patterns():
        spec = SIGNAL_CONDITIONS[signal_id]
        assert spec["field"] == "attachment_name"
        assert spec["operator"] == "regex"
        assert pattern.pattern == spec["value"]

    for signal_id, pattern in text_detection_patterns():
        spec = SIGNAL_CONDITIONS[signal_id]
        assert spec["field"] == "document_text"
        assert spec["operator"] == "regex"
        assert pattern.pattern == spec["value"]


def test_pick_groups_cover_all_non_weak_signals() -> None:
    grouped = {signal_id for group in SIGNAL_PICK_GROUPS for signal_id in group}
    for signal_id in SIGNAL_CONDITIONS:
        if signal_id in WEAK_SIGNAL_IDS or signal_id == "channel_whatsapp":
            continue
        assert signal_id in grouped
