"""Unit tests for Slack DM poll helpers."""

from __future__ import annotations

from app.services.ingest.slack_poll_service import _message_event_id, _parse_slack_ts


def test_message_event_id_stable() -> None:
    a = _message_event_id(channel="D1", ts="1.2", file_ids=["F2", "F1"])
    b = _message_event_id(channel="D1", ts="1.2", file_ids=["F1", "F2"])
    assert a == b
    assert a.startswith("poll:D1:1.2:")


def test_parse_slack_ts() -> None:
    dt = _parse_slack_ts("1788438314.377099")
    assert dt is not None
    assert dt.year >= 2026
    assert _parse_slack_ts("bad") is None
