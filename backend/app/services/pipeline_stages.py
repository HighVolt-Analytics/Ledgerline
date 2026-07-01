"""Pipeline stage computation from invoice state + audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_ref_service import display_document_ref
from app.services.publish_service import is_published_from_audit_logs

MATRIX_STAGES = ("Received", "Parsed", "Validated", "Mapped", "Approved", "Posted")
StageState = Literal["done", "pending", "fail", "skipped"]
_PROCESSING_COMPLETE_EVENTS = (
    "vault_stored",
    "purchase_document_processed",
    "invoice_processed",
)


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
    from app.services.validator import normalize_stored_validation_results

    raw = inv.validation_results
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return normalize_stored_validation_results(parsed)
    if isinstance(raw, list):
        return normalize_stored_validation_results(raw)
    return []


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


def _processing_complete_log(logs: list[AuditLog]) -> AuditLog | None:
    return _latest_log(logs, *_PROCESSING_COMPLETE_EVENTS)


def _processing_finished(inv: Invoice, logs: list[AuditLog]) -> bool:
    """True when the document finished the pipeline (DB status or terminal audit)."""
    if inv.status == InvoiceStatus.PROCESSED:
        return True
    if inv.status in (InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED):
        return False
    return _processing_complete_log(logs) is not None


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
    terminal_log = _processing_complete_log(logs)
    processing_finished = _processing_finished(inv, logs)

    source = _source_label(inv)
    received_via = inv.email_sender or source
    received_at = received_log.created_at if received_log else inv.created_at

    parse_conf = None
    if parsed_log and parsed_log.detail:
        parse_conf = parsed_log.detail.get("confidence")
    parsed_at = parsed_log.created_at if parsed_log else None
    if parsed_at is None and (_stage_index(inv.status) >= 1 or processing_finished):
        parsed_at = terminal_log.created_at if terminal_log else inv.created_at

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
    if processing_finished:
        if terminal_log and terminal_log.event == "vault_stored":
            validation_text, validation_state = "Stored in document vault", "done"
        elif terminal_log and terminal_log.event == "purchase_document_processed":
            validation_text, validation_state = "Supporting document processed", "done"
        elif validation_state != "fail":
            validation_text, validation_state = "Passed", "done"
        validated_at = validated_at or (terminal_log.created_at if terminal_log else inv.created_at)

    account = inv.account_name or ("Pending" if awaiting_reparse else "Suspense Account")
    mapped_at = mapped_log.created_at if mapped_log else None
    if mapped_at is None and (_stage_index(inv.status) >= 3 and not awaiting_reparse or processing_finished):
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
    elif processing_finished:
        approved_at = terminal_log.created_at if terminal_log else inv.created_at
        approved_detail = "System · Within policy"
        approved_state = "done"
    elif inv.status == InvoiceStatus.EXCEPTION:
        approved_detail = "Awaiting review"

    published_at: datetime | None = None
    published_detail = "Pending"
    published_state: StageState = "pending"
    doc_ref = display_document_ref(inv)
    if is_published_from_audit_logs(logs):
        published_log = _latest_log(logs, "invoice_published_to_ledger")
        published_at = published_log.created_at if published_log else None
        actor = _actor_name(published_log.detail if published_log else None)
        published_detail = f"{actor} · {doc_ref}" if actor else doc_ref
        published_state = "done"
    elif inv.status == InvoiceStatus.PROCESSED:
        published_at = published_log.created_at if published_log else inv.created_at
        published_detail = f"{doc_ref} · ready to post"
        published_state = "pending"
    elif processing_finished:
        published_at = terminal_log.created_at if terminal_log else inv.created_at
        if terminal_log and terminal_log.event == "vault_stored":
            published_detail = f"{doc_ref} · archived in vault"
        else:
            published_detail = f"{doc_ref} · ready to post"
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

    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        from app.services.audit_change_summary import summarize_audit_change

        dup_log = _latest_log(
            logs,
            "duplicate_skipped",
            "duplicate_in_progress",
            "duplicate_reingest_rejected",
        )
        dup_detail = "Duplicate file skipped"
        if dup_log:
            dup_detail = summarize_audit_change(
                dup_log.event,
                dup_log.detail if isinstance(dup_log.detail, dict) else {},
            )
        return [
            PipelineStage(
                stage="Received",
                at=received_at,
                detail=f"{source} · {received_via}",
                state="done",
            ),
            PipelineStage(
                stage="Duplicate skipped",
                at=dup_log.created_at if dup_log else inv.created_at,
                detail=dup_detail,
                state="skipped",
            ),
        ]

    parsed_state: StageState = (
        "fail"
        if parsed_log and parsed_log.event == "parsing_failed"
        else "done"
        if processing_finished
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
        if mapped_suspense and inv.status == InvoiceStatus.EXCEPTION and not processing_finished
        else "done"
        if processing_finished or _stage_index(inv.status) >= 3
        else "pending"
    )

    stages = [
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
            stage="Posted",
            at=published_at,
            detail=f"Ledger · {published_detail}",
            state=published_state,
        ),
    ]

    dup_log = _latest_log(logs, "duplicate_in_progress", "duplicate_skipped")
    if dup_log is not None:
        from app.services.audit_change_summary import summarize_audit_change

        stages.append(
            PipelineStage(
                stage="Duplicate detected",
                at=dup_log.created_at,
                detail=summarize_audit_change(
                    dup_log.event,
                    dup_log.detail if isinstance(dup_log.detail, dict) else {},
                ),
                state="skipped",
            )
        )

    return stages


_SPECIAL_STAGE_LABELS: dict[str, str] = {
    "Rejected": "Rejected",
    "Duplicate skipped": "Duplicate",
    "Duplicate detected": "Duplicate",
}


def derive_current_stage(inv: Invoice, logs: list[AuditLog]) -> tuple[str, StageState]:
    """
    Single inbox label for list UIs — first blocked pipeline step, or terminal outcome.
    Uses the same rules as build_pipeline_stages / Doc. Matrix.
    """
    steps = build_pipeline_stages(inv, logs)

    for step in steps:
        if step.stage in _SPECIAL_STAGE_LABELS:
            label = _SPECIAL_STAGE_LABELS[step.stage]
            state: StageState = (
                "fail" if step.state in ("fail", "skipped") else step.state
            )
            return label, state

    by_name = {step.stage: step for step in steps}

    posted = by_name.get("Posted")
    if posted and posted.state == "done":
        return "Posted", "done"

    if _processing_finished(inv, logs):
        return "Processed", "done"

    last_done: tuple[str, StageState] | None = None
    for name in MATRIX_STAGES:
        step = by_name.get(name)
        if not step or step.state == "skipped":
            continue
        if step.state == "fail":
            return name, "fail"
        if step.state == "pending":
            return name, "pending"
        if step.state == "done":
            last_done = (name, "done")

    if last_done:
        return last_done
    return "Received", "pending"


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
