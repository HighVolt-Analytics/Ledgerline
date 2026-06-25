"""Human-readable catalogue of document-type recognition signals."""

from __future__ import annotations

from app.services.recognition_signal_registry import (
    PLAYBOOK_RECOMMENDED_IDENTITY,
    RECOGNITION_SIGNAL_CATALOG,
    RecognitionSignalInfo,
    WEAK_SIGNAL_IDS,
    RecognitionSignalId,
)

__all__ = [
    "RecognitionSignalId",
    "RecognitionSignalInfo",
    "WEAK_SIGNAL_IDS",
    "RECOGNITION_SIGNAL_CATALOG",
    "PLAYBOOK_RECOMMENDED_IDENTITY",
    "describe_signal",
    "describe_signals",
    "suggest_missing_identity_signals",
    "weak_signal_warning",
]


def describe_signal(signal_id: RecognitionSignalId, *, detected: bool = True) -> dict[str, str]:
    info = RECOGNITION_SIGNAL_CATALOG.get(signal_id)
    if info is None:
        return {
            "signal_id": signal_id,
            "label": signal_id.replace("_", " ").title(),
            "hint": "",
            "channel": "unknown",
            "strength": "strong" if signal_id not in WEAK_SIGNAL_IDS else "weak",
            "example": "",
            "detected": detected,
        }
    return {
        "signal_id": info.signal_id,
        "label": info.label,
        "hint": info.hint,
        "channel": info.channel,
        "strength": info.strength,
        "example": info.example,
        "detected": detected,
    }


def describe_signals(signal_ids: list[RecognitionSignalId]) -> list[dict[str, str]]:
    return [describe_signal(signal_id, detected=True) for signal_id in signal_ids]


def suggest_missing_identity_signals(
    detected: frozenset[RecognitionSignalId],
    *,
    playbook: str,
    document_heading: str | None = None,
    document_text: str = "",
) -> list[dict[str, str]]:
    """Recommend strong identity signals not yet detected."""
    from app.services.document_type_recognition_signals import identity_signals
    from app.services.heading_kind_recognition import resolve_playbook_profile

    if identity_signals(detected):
        return []

    resolved_playbook = resolve_playbook_profile(
        detected,
        heading=document_heading,
        document_text=document_text,
    )
    recommended = PLAYBOOK_RECOMMENDED_IDENTITY.get(
        (resolved_playbook or playbook or "").strip().lower(),
        PLAYBOOK_RECOMMENDED_IDENTITY["direct_expense"],
    )
    missing: list[dict[str, str]] = []
    heading = (document_heading or "").strip()
    for signal_id in recommended:
        if signal_id in detected:
            continue
        if signal_id in WEAK_SIGNAL_IDS:
            continue
        row = describe_signal(signal_id, detected=False)
        if signal_id == "heading_invoice" and heading:
            row["hint"] = (
                f'{row["hint"]} — your heading is "{heading}"; '
                "ensure it says Tax Invoice or rename file"
            )
        elif signal_id == "filename_invoice":
            row["hint"] = f'{row["hint"]} — try renaming upload to include invoice or inv'
        elif signal_id == "text_import" and heading:
            row["hint"] = (
                f'{row["hint"]} — your heading is "{heading}"; '
                "body OCR should include permit/customs wording"
            )
        elif signal_id == "filename_import":
            row["hint"] = (
                f'{row["hint"]} — try renaming to include customs, clearance, or import'
            )
        missing.append(row)
    return missing[:4]


def weak_signal_warning(detected: frozenset[RecognitionSignalId]) -> str | None:
    """Human note when only weak field signals were detected."""
    from app.services.document_type_recognition_signals import identity_signals

    if identity_signals(detected):
        return None
    weak_only = detected & WEAK_SIGNAL_IDS
    if not weak_only:
        return None
    labels = [describe_signal(signal_id)["label"] for signal_id in sorted(weak_only)]
    joined = ", ".join(labels)
    return (
        f"Add stronger identity signals (see Suggested signals below) — "
        f"{joined} alone matches many document types."
    )
