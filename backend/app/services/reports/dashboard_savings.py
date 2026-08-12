"""Effort-credit savings model for dashboard executive / capture-source KPIs.

Manual channel baselines estimate human effort avoided. AI outcome applies a
credit factor (full STP vs assisted). Cost uses the tenant labour rate
(default DEFAULT_LABOR_RATE_PER_HOUR in books currency).
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

# Effort-credit factors: STP = AI finished alone; assisted = PROCESSED with human touch.
STP_CREDIT = 1.0
ASSISTED_CREDIT = 0.5

# Default fully-loaded labour rate (tenant books currency units per hour).
DEFAULT_LABOR_RATE_PER_HOUR = 45.0
# Back-compat alias used by older imports / tests.
LABOR_RATE_PER_HOUR = DEFAULT_LABOR_RATE_PER_HOUR


def baseline_minutes(channel: CaptureChannel | str | None) -> int:
    key = (channel or "").strip().lower()
    if key in MANUAL_BASELINE_MINUTES:
        return MANUAL_BASELINE_MINUTES[key]  # type: ignore[index]
    return DEFAULT_MANUAL_BASELINE_MINUTES


def credit_factor(*, is_processed: bool, is_stp: bool) -> float:
    """Return effort-credit multiplier for one document."""
    if not is_processed:
        return 0.0
    return STP_CREDIT if is_stp else ASSISTED_CREDIT


def minutes_saved_per_doc(
    channel: CaptureChannel | str | None,
    *,
    credit_factor: float,
) -> int:
    """Return estimated minutes saved vs manual baseline for one document."""
    if credit_factor <= 0:
        return 0
    return max(0, int(round(baseline_minutes(channel) * credit_factor)))


def time_saved_minutes(
    document_count: int,
    channel: CaptureChannel | str | None,
    *,
    credit_factor: float,
) -> int:
    if document_count <= 0 or credit_factor <= 0:
        return 0
    return minutes_saved_per_doc(channel, credit_factor=credit_factor) * document_count


def manual_minutes(document_count: int, channel: CaptureChannel | str | None) -> int:
    if document_count <= 0:
        return 0
    return baseline_minutes(channel) * document_count


def cost_saved_from_minutes(
    time_saved_min: int,
    *,
    labor_rate_per_hour: float = DEFAULT_LABOR_RATE_PER_HOUR,
) -> int:
    if time_saved_min <= 0:
        return 0
    rate = max(0.0, float(labor_rate_per_hour))
    return int(round((time_saved_min / 60.0) * rate))


def hours_label(time_saved_min: int) -> str:
    hours = time_saved_min / 60.0
    if hours < 10:
        return f"{hours:.1f} hours recovered"
    return f"{hours:.0f} hours recovered"
