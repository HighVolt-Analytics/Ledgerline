"""Pipeline stage computation from invoice state + audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus

MATRIX_STAGES = ("Received", "Parsed", "Validated", "Mapped", "Approved", "Published")
StageState = Literal["done", "pending", "fail", "skipped"]


class PipelineStage(BaseModel):
    stage: str
    at: datetime | None = None
    detail: str
    state: StageState


def _relative_time(at: datetime | None) -> str:
    if at is None:
        return "—"
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - at
    mins = int(diff.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


def _latest_log(logs: list[AuditLog], *events: str) -> AuditLog | None:
    return _latest_event_log(logs, events)


def _latest_event_log(logs: list[AuditLog], events: tuple[str, ...] | list[str]) -> AuditLog | None:
    best: AuditLog | None = None
    for entry in logs:
        if entry.event not in events:
            continue
        if best is None or entry.created_at > best.created_at:
            best = entry
    return best


def _is_after(entry: AuditLog | None, pivot: AuditLog | None) -> bool:
    if entry is None:
        return False
    if pivot is None:
        return True
    return entry.created_at >= pivot.created_at


def _validation_detail(inv: Invoice, logs: list[AuditLog]) -> tuple[str, StageState]:
    failed = [
        r for r in _validation_results(inv) if not r.get("skipped") and not r.get("passed")
    ]
    if failed:
        msg = failed[0].get("message", "Failed checks")
        return str(msg), "fail"
    if _validation_results(inv):
        return "Passed", "done"

    latest_approve = _latest_event_log(logs, ["invoice_approved"])
    latest_passed = _latest_event_log(logs, ["validation_passed"])
    latest_failed = _latest_event_log(logs, ["validation_failed"])
    latest_hold = _latest_event_log(logs, ["vendor_registration_hold"])

    if (
        latest_hold
        and _is_after(latest_hold, latest_approve)
        and inv.status == InvoiceStatus.EXCEPTION
    ):
        return "Vendor registration hold", "fail"

    if latest_passed and latest_failed:
        if latest_passed.created_at > latest_failed.created_at and _is_after(
            latest_passed, latest_approve
        ):
            return "Passed", "done"
        if latest_failed.created_at >= latest_passed.created_at and _is_after(
            latest_failed, latest_approve
        ):
            return "Failed checks", "fail"
    elif latest_passed and _is_after(latest_passed, latest_approve):
        return "Passed", "done"
    elif latest_failed and _is_after(latest_failed, latest_approve):
        return "Failed checks", "fail"

    if inv.status in (
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    ):
        return "In progress", "pending"

    if inv.status == InvoiceStatus.EXCEPTION:
        return "Routed to review", "fail"
    return "Pending", "pending"


def _validation_results(inv: Invoice) -> list[dict[str, Any]]:
    raw = inv.validation_results
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return raw if isinstance(raw, list) else []


def _stage_index(status: InvoiceStatus) -> int:
    mapping = {
        InvoiceStatus.PENDING: 0,
        InvoiceStatus.PARSING: 1,
        InvoiceStatus.VALIDATING: 2,
        InvoiceStatus.MAPPING: 3,
        InvoiceStatus.JOURNALING: 3,
        InvoiceStatus.RECONCILING: 3,
        InvoiceStatus.PROCESSED: 5,
        InvoiceStatus.EXCEPTION: 2,
        InvoiceStatus.REJECTED: 0,
        InvoiceStatus.DUPLICATE_SKIPPED: 0,
    }
    return mapping.get(status, 0)


def _source_label(inv: Invoice) -> str:
    sender = (inv.email_sender or "").lower()
    if "onedrive" in sender or "sharepoint" in sender:
        return "OneDrive"
    if inv.email_sender or inv.connected_mailbox_id:
        return "Email"
    return "Direct upload"


def _actor_name(detail: dict[str, Any] | None) -> str | None:
    if not detail:
        return None
    name = detail.get("actor_name")
    return str(name) if name else None


def build_pipeline_stages(inv: Invoice, logs: list[AuditLog]) -> list[PipelineStage]:
    """Six-step narrative for audit UI."""
    received_log = _latest_log(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached")
    parsed_log = _latest_log(logs, "parse_completed", "invoice_parsed", "parsing_failed")
    validated_log = _latest_log(logs, "validation_passed", "validation_failed")
    mapped_log = _latest_log(logs, "mapping_applied")
    approved_log = _latest_log(logs, "invoice_approved")
    published_log = _latest_log(logs, "invoice_published_to_ledger", "invoice_processed")

    source = _source_label(inv)
    received_via = inv.email_sender or source
    received_at = received_log.created_at if received_log else inv.created_at

    parse_conf = None
    if parsed_log and parsed_log.detail:
        parse_conf = parsed_log.detail.get("confidence")
    parsed_at = parsed_log.created_at if parsed_log else None
    if parsed_at is None and _stage_index(inv.status) >= 1:
        parsed_at = inv.created_at

    awaiting_reparse = (
        inv.status == InvoiceStatus.PENDING
        and not (inv.vendor or inv.invoice_no)
        and parsed_log is not None
        and parsed_log.event != "parsing_failed"
    )

    validation_text, validation_state = _validation_detail(inv, logs)
    if awaiting_reparse:
        validation_text, validation_state = "Pending", "pending"
    validated_at = validated_log.created_at if validated_log else None
    if validated_at is None and _stage_index(inv.status) >= 2 and not awaiting_reparse:
        validated_at = parsed_at or inv.created_at

    account = inv.account_name or ("Pending" if awaiting_reparse else "Suspense Account")
    mapped_at = mapped_log.created_at if mapped_log else None
    if mapped_at is None and _stage_index(inv.status) >= 3 and not awaiting_reparse:
        mapped_at = validated_at or inv.created_at
    mapped_suspense = (
        not awaiting_reparse and inv.account_name and "suspense" in inv.account_name.lower()
    )

    approved_at: datetime | None = None
    approved_detail = "Pending policy"
    approved_state: StageState = "pending"
    if approved_log:
        approved_at = approved_log.created_at
        actor = _actor_name(approved_log.detail)
        if inv.status == InvoiceStatus.PROCESSED:
            approved_detail = f"{actor} · Approved" if actor else "Approved for processing"
            approved_state = "done"
        elif inv.status in (
            InvoiceStatus.PENDING,
            InvoiceStatus.PARSING,
            InvoiceStatus.VALIDATING,
            InvoiceStatus.MAPPING,
            InvoiceStatus.JOURNALING,
            InvoiceStatus.RECONCILING,
        ):
            approved_detail = f"{actor} · Processing" if actor else "Approved · processing"
            approved_state = "pending"
        elif inv.status == InvoiceStatus.EXCEPTION:
            approved_detail = (
                f"{actor} · Reprocess needed" if actor else "Approved · reprocess needed"
            )
            approved_state = "pending"
        else:
            approved_detail = f"{actor} · Approved" if actor else "Approved for processing"
            approved_state = "done"
    elif inv.status == InvoiceStatus.PROCESSED:
        approved_at = published_log.created_at if published_log else inv.created_at
        approved_detail = "System · Within policy"
        approved_state = "done"
    elif inv.status == InvoiceStatus.EXCEPTION:
        approved_detail = "Awaiting review"

    published_at: datetime | None = None
    published_detail = "Pending"
    published_state: StageState = "pending"
    doc_ref = inv.invoice_no or f"DOC-{inv.id:04d}"
    if published_log and published_log.event == "invoice_published_to_ledger":
        published_at = published_log.created_at
        actor = _actor_name(published_log.detail)
        published_detail = f"{actor} · {doc_ref}" if actor else doc_ref
        published_state = "done"
    elif inv.status == InvoiceStatus.PROCESSED:
        published_at = published_log.created_at if published_log else inv.created_at
        published_detail = f"{doc_ref} · ready to publish"
        published_state = "pending"

    if inv.status == InvoiceStatus.REJECTED:
        rejected_log = _latest_log(logs, "invoice_rejected")
        actor = _actor_name(rejected_log.detail if rejected_log else None)
        reject_detail = f"{actor} · Document rejected" if actor else "Document rejected"
        return [
            PipelineStage(
                stage="Received",
                at=received_at,
                detail=f"{source} · {received_via}",
                state="done",
            ),
            PipelineStage(
                stage="Rejected",
                at=rejected_log.created_at if rejected_log else None,
                detail=reject_detail,
                state="fail",
            ),
        ]

    parsed_state: StageState = (
        "fail"
        if parsed_log and parsed_log.event == "parsing_failed"
        else "pending"
        if awaiting_reparse
        else "done"
        if _stage_index(inv.status) >= 1
        else "pending"
    )
    parsed_detail = (
        "Could not read document"
        if parsed_log and parsed_log.event == "parsing_failed"
        else "Queued for re-parse"
        if awaiting_reparse
        else f"OCR complete · {parse_conf}% confidence"
        if parse_conf is not None
        else "OCR complete"
        if _stage_index(inv.status) >= 1
        else "Pending"
    )

    mapped_state: StageState = (
        "fail"
        if mapped_suspense and inv.status == InvoiceStatus.EXCEPTION
        else "done"
        if _stage_index(inv.status) >= 3
        else "pending"
    )

    return [
        PipelineStage(
            stage="Received",
            at=received_at,
            detail=f"{source} · {received_via}",
            state="done",
        ),
        PipelineStage(
            stage="Parsed",
            at=parsed_at,
            detail=parsed_detail,
            state=parsed_state,
        ),
        PipelineStage(
            stage="Validated",
            at=validated_at,
            detail=f"Tax & totals checked · {validation_text}",
            state=validation_state,
        ),
        PipelineStage(
            stage="Mapped",
            at=mapped_at,
            detail=f"Rule book applied · {account}",
            state=mapped_state,
        ),
        PipelineStage(
            stage="Approved",
            at=approved_at,
            detail=approved_detail,
            state=approved_state,
        ),
        PipelineStage(
            stage="Published",
            at=published_at,
            detail=f"Ledger · {published_detail}",
            state=published_state,
        ),
    ]


def build_matrix_cells(inv: Invoice, logs: list[AuditLog]) -> list[dict[str, str]]:
    """Matrix grid cells derived from pipeline stages (plain dicts for API schemas)."""
    steps = build_pipeline_stages(inv, logs)
    by_name = {step.stage: step for step in steps}
    cells: list[dict[str, str]] = []

    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        for i, stage in enumerate(MATRIX_STAGES):
            cells.append(
                {
                    "stage": stage,
                    "state": "fail" if i == 0 else "pending",
                    "when": "—",
                    "detail": "Duplicate skipped",
                }
            )
        return cells

    for stage in MATRIX_STAGES:
        step = by_name.get(stage)
        if step:
            state: StageState = step.state if step.state != "skipped" else "pending"
            cells.append(
                {
                    "stage": stage,
                    "state": state,
                    "when": _relative_time(step.at),
                    "detail": step.detail,
                }
            )
            continue
        cells.append(
            {"stage": stage, "state": "pending", "when": "—", "detail": "Pending"}
        )

    return cells


def pipeline_steps_for_api(steps: list[PipelineStage]) -> list[dict[str, Any]]:
    """Serialize with human-readable relative times for the frontend."""
    return [
        {
            "stage": step.stage,
            "at": step.at.isoformat() if step.at else None,
            "when": _relative_time(step.at),
            "detail": step.detail,
            "state": step.state,
        }
        for step in steps
    ]
