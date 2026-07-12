"""Per-invoice pipeline step skip catalog and helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.invoice import Invoice

ProcessingOverrideStepId = Literal[
    "image_quality",
    "classification",
    "field_confidence",
    "vendor_drift",
    "playbook",
    "validation",
    "mapping_review",
    "vendor_registration",
    "line_gl_mapping",
]

SKIPPABLE_STEP_IDS: frozenset[str] = frozenset(
    {
        "image_quality",
        "classification",
        "field_confidence",
        "vendor_drift",
        "playbook",
        "validation",
        "mapping_review",
        "vendor_registration",
        "line_gl_mapping",
    }
)


class ProcessingOverrideStepInfo(BaseModel):
    step_id: str
    label: str
    hint: str


PROCESSING_OVERRIDE_STEPS: tuple[ProcessingOverrideStepInfo, ...] = (
    ProcessingOverrideStepInfo(
        step_id="image_quality",
        label="Image quality gate",
        hint="Skip low OCR text / sparse scan checks on reprocess.",
    ),
    ProcessingOverrideStepInfo(
        step_id="classification",
        label="Classify + confidence gate",
        hint="Use the document type already on this invoice; requires DT to be set.",
    ),
    ProcessingOverrideStepInfo(
        step_id="field_confidence",
        label="Field confidence review",
        hint="Continue when extracted fields are below confidence threshold.",
    ),
    ProcessingOverrideStepInfo(
        step_id="vendor_drift",
        label="Vendor classification drift",
        hint="Ignore vendor DT drift warnings on reprocess.",
    ),
    ProcessingOverrideStepInfo(
        step_id="playbook",
        label="Playbook / bundle gates",
        hint="Skip playbook mandatory-field, bundle linkage, and missing-PO holds.",
    ),
    ProcessingOverrideStepInfo(
        step_id="validation",
        label="Validation rules",
        hint="Bypass configured VR checks on reprocess.",
    ),
    ProcessingOverrideStepInfo(
        step_id="mapping_review",
        label="GL mapping review",
        hint="Apply mapping without manual GL review.",
    ),
    ProcessingOverrideStepInfo(
        step_id="vendor_registration",
        label="Vendor registration hold",
        hint="Continue when the vendor is not yet in the vendor registry.",
    ),
    ProcessingOverrideStepInfo(
        step_id="line_gl_mapping",
        label="Line GL mapping",
        hint="Skip LLM sub-ledger assignment for line items.",
    ),
)


class ProcessingOverridesPayload(BaseModel):
    skip_steps: list[str] = Field(default_factory=list)


def normalise_processing_overrides(
    raw: dict[str, Any] | None,
) -> ProcessingOverridesPayload:
    if not raw or not isinstance(raw, dict):
        return ProcessingOverridesPayload()
    steps = raw.get("skip_steps")
    if not isinstance(steps, list):
        return ProcessingOverridesPayload()
    cleaned = [str(s).strip() for s in steps if str(s).strip() in SKIPPABLE_STEP_IDS]
    return ProcessingOverridesPayload(skip_steps=sorted(set(cleaned)))


def validate_skip_steps(skip_steps: list[str]) -> list[str]:
    unknown = [s for s in skip_steps if s not in SKIPPABLE_STEP_IDS]
    if unknown:
        raise ValueError(
            f"Unknown processing override step(s): {', '.join(sorted(unknown))}"
        )
    return sorted(set(skip_steps))


def skip_steps_for(invoice: Invoice) -> frozenset[str]:
    payload = normalise_processing_overrides(getattr(invoice, "processing_overrides", None))
    return frozenset(payload.skip_steps)


def should_skip(invoice: Invoice, step_id: str) -> bool:
    return step_id in skip_steps_for(invoice)


def override_bypasses_purchase_hold(invoice: Invoice) -> bool:
    """Skipping playbook also bypasses missing-PO / awaiting_po purchase holds."""
    return should_skip(invoice, "playbook")


def clear_processing_overrides(invoice: Invoice) -> None:
    invoice.processing_overrides = None


def serialise_processing_overrides(skip_steps: list[str]) -> dict[str, list[str]] | None:
    validated = validate_skip_steps(skip_steps)
    if not validated:
        return None
    return {"skip_steps": validated}


def set_deferred_full_reset(invoice: Invoice) -> None:
    raw = dict(getattr(invoice, "processing_overrides", None) or {})
    raw["deferred_full_reset"] = True
    invoice.processing_overrides = raw


def has_deferred_full_reset(invoice: Invoice) -> bool:
    raw = getattr(invoice, "processing_overrides", None)
    return isinstance(raw, dict) and bool(raw.get("deferred_full_reset"))


def consume_deferred_full_reset(invoice: Invoice) -> bool:
    raw = getattr(invoice, "processing_overrides", None)
    if not isinstance(raw, dict):
        return False
    if not raw.get("deferred_full_reset"):
        return False
    updated = dict(raw)
    updated.pop("deferred_full_reset", None)
    invoice.processing_overrides = updated or None
    return True


def clear_deferred_full_reset(invoice: Invoice) -> None:
    raw = getattr(invoice, "processing_overrides", None)
    if not isinstance(raw, dict) or "deferred_full_reset" not in raw:
        return
    updated = dict(raw)
    updated.pop("deferred_full_reset", None)
    invoice.processing_overrides = updated or None
