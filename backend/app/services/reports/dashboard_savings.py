"""Documented savings model for dashboard executive / capture-source KPIs.

No per-tenant cost settings yet — constants match the dashboard UI placeholder intent.
"""

from __future__ import annotations

from typing import Literal

CaptureChannel = Literal["email", "whatsapp", "viber", "upload"]

# Manual processing baseline minutes per document by inbound channel.
MANUAL_BASELINE_MINUTES: dict[CaptureChannel, int] = {
    "email": 12,
    "whatsapp": 15,
    "viber": 12,
    "upload": 11,
}
DEFAULT_MANUAL_BASELINE_MINUTES = 15

# Fully-loaded labour rate used to convert time saved → currency units.
LABOR_RATE_PER_HOUR = 45


def baseline_minutes(channel: CaptureChannel | str | None) -> int:
    key = (channel or "").strip().lower()
    if key in MANUAL_BASELINE_MINUTES:
        return MANUAL_BASELINE_MINUTES[key]  # type: ignore[index]
    return DEFAULT_MANUAL_BASELINE_MINUTES


def minutes_saved_per_doc(
    channel: CaptureChannel | str | None,
    *,
    actual_processing_minutes: float | None,
) -> int:
    """Return estimated minutes saved vs manual baseline for one document."""
    baseline = baseline_minutes(channel)
    actual = 0.0 if actual_processing_minutes is None else max(0.0, actual_processing_minutes)
    return max(0, int(round(baseline - actual)))


def time_saved_minutes(
    document_count: int,
    channel: CaptureChannel | str | None,
    *,
    actual_processing_minutes: float | None,
) -> int:
    if document_count <= 0:
        return 0
    return minutes_saved_per_doc(
        channel, actual_processing_minutes=actual_processing_minutes
    ) * document_count


def manual_minutes(document_count: int, channel: CaptureChannel | str | None) -> int:
    if document_count <= 0:
        return 0
    return baseline_minutes(channel) * document_count


def cost_saved_from_minutes(time_saved_min: int) -> int:
    if time_saved_min <= 0:
        return 0
    return int(round((time_saved_min / 60.0) * LABOR_RATE_PER_HOUR))


def hours_label(time_saved_min: int) -> str:
    hours = time_saved_min / 60.0
    if hours < 10:
        return f"{hours:.1f} hours recovered"
    return f"{hours:.0f} hours recovered"
