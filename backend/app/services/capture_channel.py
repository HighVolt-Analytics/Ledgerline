"""Infer submission channel from capture metadata (email / mobile)."""

from __future__ import annotations

import re


def normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def infer_capture_channel(sender: str | None) -> str:
    """Return email | mob | unknown for team expense channel rules."""
    if not sender or not sender.strip():
        return "unknown"
    text = sender.strip()
    if "@" in text:
        return "email"
    if len(normalize_phone(text)) >= 8:
        return "mob"
    return "unknown"


def channel_rule_matches(rule_channel: str | None, actual: str) -> bool:
    if not rule_channel or rule_channel.strip().lower() in {"", "any"}:
        return True
    expected = rule_channel.strip().lower()
    actual_norm = actual.strip().lower()
    if expected in {"email", "em"}:
        return actual_norm == "email"
    if expected in {"mob", "mobile", "whatsapp", "wa", "viber", "phone"}:
        return actual_norm == "mob"
    return expected == actual_norm
