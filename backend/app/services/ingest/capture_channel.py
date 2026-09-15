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


def is_known_messaging_sender(
    sender: str | None,
    employees: list,
) -> bool:
    """True when sender matches an employee WhatsApp or Viber number."""
    phone = normalize_phone(sender)
    if not phone:
        return False
    for employee in employees:
        for field in (
            getattr(employee, "whatsapp_number", None),
            getattr(employee, "whatsapp_number_2", None),
            getattr(employee, "viber_number", None),
        ):
            if field and normalize_phone(str(field)) == phone:
                return True
    return False


def is_staff_claim_sender(sender: str | None, employees: list) -> bool:
    """Mob channel or known employee messaging identity (expense book guard)."""
    if infer_capture_channel(sender) == "mob":
        return True
    return is_known_messaging_sender(sender, employees)


APP_CAPTURE_ALIASES = frozenset({"app", "mobile", "mob"})
LIST_CAPTURE_SOURCES = frozenset({"upload", "email", "whatsapp", "viber", "slack", "app"})


def stored_capture_source_for_upload(value: str | None) -> str:
    """Desktop uploads stay ``upload``; mobile client sends app/mobile/mob → ``app``."""
    raw = (value or "upload").strip().lower()
    if raw in APP_CAPTURE_ALIASES:
        return "app"
    return "upload"


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
