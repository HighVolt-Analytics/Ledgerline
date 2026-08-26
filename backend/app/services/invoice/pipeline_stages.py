"""Pipeline stage computation from invoice state + audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_ref_service import display_document_ref
from app.services.integration.publish_service import is_published_from_audit_logs

MATRIX_STAGES = ("Received", "Parsed", "Validated", "Approved", "Mapped", "Posted")
# Compact Summary grid follows finance continuum:
# Validate → Match/Approve → Map GL → Post (Match folds onto Approved).
_INBOX_STAGE_WALK = (
    "Received",
    "Parsed",
    "Validated",
    "Match",
    "Approved",
    "Mapped",
    "Journal",
    "Reconcile",
    "Posted",
)
StageState = Literal["done", "pending", "fail", "skipped"]
PipelineActivePath = Literal["understood", "not_understood", "unknown"]

# Audit-tab stage membership (dual Processing sub-tabs).
UNDERSTOOD_AUDIT_STAGES: frozenset[str] = frozenset(
    {
        "Received",
        "Duplicate",
        "Storage",
        "File validity",
        "Vision understand",
        "Vision header",
        "Type suggest",
        "DT mapped",
        "DT fields",
        "Bundle",
        "Vault",
        "Parsed",
        "Validated",
        "Approved",
        "Mapped",
        "Match",
        "Journal",
        "Reconcile",
        "Posted",
    }
)
NOT_UNDERSTOOD_AUDIT_STAGES: frozenset[str] = frozenset(
    {
        "Received",
        "Duplicate",
        "Storage",
        "File validity",
        "Vision understand",
        "Image quality",
        "Layout readiness",
        "OCR",
        "OCR quality",
        "Classified",
        "Gate",
        "Parsed",
        "Validated",
        "Mapped",
        "Approved",
        "Posted",
    }
)

_PROCESSING_COMPLETE_EVENTS = (
    "vault_stored",
    "purchase_document_processed",
    "sales_document_processed",
    "supporting_document_processed",
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


def _configured_blocker_keys(dt: str, document_types: list | None) -> list[str] | None:
    """DT extraction keys for field blockers — None when the catalogue is unknown."""
    if not document_types:
        return None
    from app.services.classification.document_type_catalog import get_document_type_definition

    defn = get_document_type_definition(dt, document_types=document_types)
    if defn is None:
        return None
    return list(defn.extraction_fields or [])


def exception_hold_reason(inv: Invoice, document_types: list | None = None) -> str:
    """Concrete reason for an exception hold — never a vague 'Routed to review'."""
    from app.services.invoice.invoice_blockers import (
        blocker_hold_reason,
        detect_invoice_blockers,
    )

    failed = [
        r for r in _validation_results(inv) if not r.get("skipped") and not r.get("passed")
    ]
    if failed:
        msg = str(failed[0].get("message") or "").strip()
        if msg:
            return msg
        rule_id = str(failed[0].get("rule") or "").strip()
        if rule_id:
            return f"Validation rule {rule_id} failed"
        return "Validation failed"

    eval_status = (inv.evaluation_status or "").strip().lower()
    route = (inv.route_target or "").strip()
    is_sales = route == "Sales Management"
    dt = (inv.document_type_code or "").strip()
    configured = _configured_blocker_keys(dt, document_types)

    if eval_status == "awaiting_classification":
        return "Document type not classified — confirm on Fields"
    if eval_status == "vision_header_review":
        from app.services.classification.document_type_catalog import (
            get_document_type_definition,
        )
        from app.services.invoice.vision_posting_continue import vision_header_gaps

        defn = (
            get_document_type_definition(dt, document_types=document_types)
            if document_types
            else None
        )
        gaps = vision_header_gaps(inv, defn)
        if gaps:
            return (
                f"Still missing on Fields: {', '.join(gaps)} — "
                "complete, then Confirm & process"
            )
        field_reason = blocker_hold_reason(
            detect_invoice_blockers(inv, configured_keys=configured)
        )
        return field_reason or "Header fields incomplete — complete Fields, then Confirm & process"
    if eval_status == "pending_vendor":
        return (
            "Customer not in master — register in Creations, then reprocess"
            if is_sales
            else "Vendor not in master — register in Creations, then reprocess"
        )
    if eval_status == "unmatched_expense_vendor":
        return "Unknown expense vendor — register vendor if needed, then reprocess"
    if eval_status == "awaiting_po":
        return "Awaiting PO linkage — link or upload the PO, then reprocess"
    if eval_status == "awaiting_so":
        return "Awaiting SO / DN linkage — link or upload, then reprocess"
    if eval_status == "pending_approval":
        return "Needs approver sign-off — open Approvals board"
    if eval_status == "needs_rescan":
        return "Poor scan quality — ask sender for a clearer PDF, then reprocess"
    if eval_status == "line_gl_review":
        return "Line GL mapping incomplete — assign sub-ledgers on Lines"
    if eval_status == "line_items_review":
        return "Line items incomplete — add or correct product lines"

    # Missing DT-listed currency / total / vendor beat default Suspense GL fallback.
    field_reason = blocker_hold_reason(
        detect_invoice_blockers(inv, configured_keys=configured)
    )
    if field_reason:
        return field_reason

    if eval_status == "needs_review":
        if not dt:
            return "Document type not confirmed — confirm on Fields"
        if not route:
            return "Routing not confirmed — set purchase, sales, or expense on Fields"
        account = f"{inv.account_name or ''} {inv.account_code or ''}".lower()
        if "suspense" in account or "unmapped" in account:
            return "Suspense / unmapped GL — assign account on Lines"
        return "Routing or coding needs confirmation — check Fields and Lines"

    if not dt:
        return "Document type not classified — confirm on Fields"
    if not route:
        return "Routing not confirmed — set purchase, sales, or expense on Fields"
    account = f"{inv.account_name or ''} {inv.account_code or ''}".lower()
    if "suspense" in account or "unmapped" in account:
        return "Suspense / unmapped GL — assign account on Lines"
    if eval_status == "auto_coded":
        return "Posting halted after coding — check Audit for the blocker"

    return "Needs manual review — open document and check Fields, Audit, or Lines"


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
        return exception_hold_reason(inv), "fail"
    return "Pending", "pending"


def _validation_results(inv: Invoice) -> list[dict[str, Any]]:
    from app.services.rule_book.validator import normalize_stored_validation_results

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


def _early_pipeline_stages(inv: Invoice, logs: list[AuditLog]) -> list[PipelineStage]:
    """Pre-extract phases when the strict pipeline audit trail exists.

    Branches on the latest vision-understand result so the Audit tab shows either the
    can-understand (vision header) flow or the cannot-understand (legacy OCR) flow —
    never a mix of both from prior reprocesses.
    """
    storage_log = _latest_log(logs, "storage_verified")
    if storage_log is None:
        return []

    fv_pass = _latest_log(logs, "file_validity_passed")
    fv_fail = _latest_log(logs, "file_validity_failed")
    fv_log = fv_pass or fv_fail

    vu_pass = _latest_log(logs, "vision_understand_passed")
    vu_fail = _latest_log(logs, "vision_understand_failed")
    if vu_pass and vu_fail:
        vu_log = vu_pass if _is_after(vu_pass, vu_fail) else vu_fail
    else:
        vu_log = vu_pass or vu_fail
    vision_can = bool(vu_log and vu_log.event == "vision_understand_passed")
    vision_cannot = bool(vu_log and vu_log.event == "vision_understand_failed")

    def _on_current_branch(entry: AuditLog | None) -> bool:
        """Keep events from the active understand decision onward."""
        if entry is None:
            return False
        if vu_log is None:
            return True
        return _is_after(entry, vu_log)

    vh_pass = _latest_log(logs, "vision_header_extracted")
    vh_fail = _latest_log(logs, "vision_header_extract_failed")
    if vh_pass and vh_fail:
        vh_log = vh_pass if _is_after(vh_pass, vh_fail) else vh_fail
    else:
        vh_log = vh_pass or vh_fail

    ts_pass = _latest_log(logs, "vision_type_suggested")
    ts_fail = _latest_log(logs, "vision_type_suggest_failed")
    if ts_pass and ts_fail:
        ts_log = ts_pass if _is_after(ts_pass, ts_fail) else ts_fail
    else:
        ts_log = ts_pass or ts_fail

    dtf_pass = _latest_log(logs, "vision_dt_fields_extracted")
    dtf_fail = _latest_log(logs, "vision_dt_fields_extract_failed")
    if dtf_pass and dtf_fail:
        dtf_log = dtf_pass if _is_after(dtf_pass, dtf_fail) else dtf_fail
    else:
        dtf_log = dtf_pass or dtf_fail

    vision_pending = _latest_log(logs, "vision_path_pending")

    iq_pass = _latest_log(logs, "image_quality_passed")
    iq_fail = _latest_log(logs, "image_quality_failed")
    iq_log = iq_pass or iq_fail
    layout_log = _latest_log(logs, "layout_readiness_evaluated")
    ocr_log = _latest_log(logs, "ocr_completed")
    quality_pass = _latest_log(logs, "ocr_quality_confirm_passed") or _latest_log(
        logs, "image_quality_gate_passed"
    )
    quality_fail = _latest_log(logs, "ocr_quality_confirm_failed") or _latest_log(
        logs, "image_quality_gate_failed"
    )
    quality_log = quality_pass or quality_fail
    classify_log = _latest_log(logs, "llm_classified")
    gate_pass = _latest_log(logs, "classification_gate_passed")
    gate_fail = _latest_log(logs, "classification_gate_failed")
    resolved = _latest_log(logs, "classification_resolved")
    if gate_pass and gate_fail:
        gate_log = gate_pass if _is_after(gate_pass, gate_fail) else gate_fail
    else:
        gate_log = gate_pass or gate_fail

    def _provider_detail(entry: AuditLog | None) -> str:
        if entry and entry.detail:
            provider = entry.detail.get("document_ai_provider")
            if provider:
                return str(provider)
        return "Document AI"

    stages: list[PipelineStage] = [
        PipelineStage(
            stage="Storage",
            at=storage_log.created_at,
            detail=f"File verified · {_provider_detail(storage_log)}",
            state="done",
        ),
    ]

    if fv_log:
        passed = fv_log.event == "file_validity_passed"
        code = (fv_log.detail or {}).get("rejection_code")
        stages.append(
            PipelineStage(
                stage="File validity",
                at=fv_log.created_at,
                detail=(
                    "Type/size/corruption checks passed"
                    if passed
                    else f"Rejected · {code or 'file_invalid'}"
                ),
                state="done" if passed else "fail",
            )
        )

    if vu_log:
        passed = vu_log.event == "vision_understand_passed"
        conf = (vu_log.detail or {}).get("confidence")
        conf_text = f"{int(float(conf) * 100)}%" if conf is not None else "—"
        stages.append(
            PipelineStage(
                stage="Vision understand",
                at=vu_log.created_at,
                detail=(
                    f"Can understand · {conf_text}"
                    if passed
                    else f"Cannot understand · legacy OCR · {conf_text}"
                ),
                state="done",
            )
        )

    # --- Understood branch: type-suggest/header → DT map → DT fields → bundle → vault ---
    if vision_can:
        if ts_log and _on_current_branch(ts_log):
            passed = ts_log.event == "vision_type_suggested"
            heading = (ts_log.detail or {}).get("document_heading") or "—"
            stages.append(
                PipelineStage(
                    stage="Type suggest",
                    at=ts_log.created_at,
                    detail=(
                        f"{heading} · suggested"
                        if passed
                        else f"Type suggest failed · {(ts_log.detail or {}).get('fail_reason') or 'error'}"
                    ),
                    state="done" if passed else "fail",
                )
            )
        if vh_log and _on_current_branch(vh_log):
            passed = vh_log.event == "vision_header_extracted"
            heading = (vh_log.detail or {}).get("document_heading") or "—"
            stages.append(
                PipelineStage(
                    stage="Vision header",
                    at=vh_log.created_at,
                    detail=(
                        f"{heading} · extracted"
                        if passed
                        else f"Header extract failed · {(vh_log.detail or {}).get('fail_reason') or 'error'}"
                    ),
                    state="done" if passed else "fail",
                )
            )
        elif (
            vision_pending
            and _on_current_branch(vision_pending)
            and not ts_log
            and not vh_log
        ):
            stages.append(
                PipelineStage(
                    stage="Type suggest",
                    at=vision_pending.created_at,
                    detail="Type suggest pending",
                    state="pending",
                )
            )

        dt_map = _latest_log(logs, "vision_document_type_mapped")
        if dt_map and _on_current_branch(dt_map):
            detail = dt_map.detail if isinstance(dt_map.detail, dict) else {}
            code = str(detail.get("code") or detail.get("document_type_code") or "—").strip()
            reason = str(detail.get("reason") or detail.get("method") or "").strip()
            dt_detail = f"{code}" + (f" · {reason}" if reason else "")
            stages.append(
                PipelineStage(
                    stage="DT mapped",
                    at=dt_map.created_at,
                    detail=dt_detail or "Document type mapped",
                    state="done" if code and code != "—" else "pending",
                )
            )
        elif (ts_log or vh_log) and (
            (ts_log and _on_current_branch(ts_log) and ts_log.event == "vision_type_suggested")
            or (vh_log and _on_current_branch(vh_log) and vh_log.event == "vision_header_extracted")
        ):
            stages.append(
                PipelineStage(
                    stage="DT mapped",
                    at=None,
                    detail="Document type pending",
                    state="pending",
                )
            )

        if dtf_log and _on_current_branch(dtf_log):
            passed = dtf_log.event == "vision_dt_fields_extracted"
            keys = (dtf_log.detail or {}).get("selected_keys") or []
            key_n = len(keys) if isinstance(keys, list) else 0
            stages.append(
                PipelineStage(
                    stage="DT fields",
                    at=dtf_log.created_at,
                    detail=(
                        f"{key_n} fields · extracted"
                        if passed
                        else f"DT extract failed · {(dtf_log.detail or {}).get('fail_reason') or 'error'}"
                    ),
                    state="done" if passed else "fail",
                )
            )

        bundle_linked = _latest_log(logs, "vision_bundle_linked")
        bundle_standalone = _latest_log(logs, "vision_bundle_standalone")
        if bundle_linked and bundle_standalone:
            bundle_log = (
                bundle_linked
                if _is_after(bundle_linked, bundle_standalone)
                else bundle_standalone
            )
        else:
            bundle_log = bundle_linked or bundle_standalone
        if bundle_log and _on_current_branch(bundle_log):
            detail = bundle_log.detail if isinstance(bundle_log.detail, dict) else {}
            if bundle_log.event == "vision_bundle_linked":
                kind = detail.get("vision_bundle_kind") or "key"
                key = detail.get("vision_bundle_key") or "—"
                bundle_detail = f"Bundled · {kind} · {key}"
            else:
                bundle_detail = "Standalone · no linkage key"
            stages.append(
                PipelineStage(
                    stage="Bundle",
                    at=bundle_log.created_at,
                    detail=bundle_detail,
                    state="done",
                )
            )

        vault_ok = _latest_log(logs, "blob_relocated")
        vault_skip = _latest_log(logs, "vault_layout_sync_skipped")
        if vault_ok and vault_skip:
            vault_log = vault_ok if _is_after(vault_ok, vault_skip) else vault_skip
        else:
            vault_log = vault_ok or vault_skip
        if vault_log and _on_current_branch(vault_log):
            detail = vault_log.detail if isinstance(vault_log.detail, dict) else {}
            book = detail.get("book") or detail.get("route_target") or "Vault"
            if vault_log.event == "blob_relocated":
                vault_detail = f"Stored · {book}"
                vault_state: StageState = "done"
            else:
                vault_detail = f"Vault sync skipped · {detail.get('reason') or 'noop'}"
                vault_state = "pending"
            stages.append(
                PipelineStage(
                    stage="Vault",
                    at=vault_log.created_at,
                    detail=vault_detail,
                    state=vault_state,
                )
            )
        elif vision_pending and _on_current_branch(vision_pending):
            path = ""
            if isinstance(vision_pending.detail, dict):
                path = str(vision_pending.detail.get("path") or "")
            stages.append(
                PipelineStage(
                    stage="Vault",
                    at=vision_pending.created_at,
                    detail="Stored in vault" if path else "Vault path pending",
                    state="done" if path else "pending",
                )
            )
        return stages

    # --- Not-understood (or pre-understand) branch: legacy OCR stack ---
    if vision_cannot or vu_log is None:
        if iq_log and _on_current_branch(iq_log):
            passed = iq_log.event == "image_quality_passed"
            sev = (iq_log.detail or {}).get("severity") or ("pass" if passed else "severe")
            stages.append(
                PipelineStage(
                    stage="Image quality",
                    at=iq_log.created_at,
                    detail=f"Visual fitness · {sev}",
                    state="done" if passed else "fail",
                )
            )

        if layout_log and _on_current_branch(layout_log):
            mode = (layout_log.detail or {}).get("ocr_mode") or "standard_di"
            stages.append(
                PipelineStage(
                    stage="Layout readiness",
                    at=layout_log.created_at,
                    detail=f"OCR route · {mode}",
                    state="done",
                )
            )

        if ocr_log and _on_current_branch(ocr_log):
            conf = (ocr_log.detail or {}).get("confidence", "high")
            stages.append(
                PipelineStage(
                    stage="OCR",
                    at=ocr_log.created_at,
                    detail=f"Layout read · {conf} confidence",
                    state="done",
                )
            )

        if quality_log and _on_current_branch(quality_log):
            passed = quality_log.event in {
                "ocr_quality_confirm_passed",
                "image_quality_gate_passed",
            }
            detail = quality_log.detail or {}
            text_len = detail.get("text_length")
            stages.append(
                PipelineStage(
                    stage="OCR quality",
                    at=quality_log.created_at,
                    detail=(
                        f"OCR readable · {text_len} chars"
                        if passed
                        else "Rescan required — poor image or sparse OCR"
                    ),
                    state="done" if passed else "fail",
                )
            )

        if classify_log and _on_current_branch(classify_log):
            detail = classify_log.detail or {}
            dt = detail.get("llm_suggested_dt") or "—"
            conf = detail.get("llm_confidence")
            conf_text = f"{int(float(conf) * 100)}%" if conf is not None else "—"
            stages.append(
                PipelineStage(
                    stage="Classified",
                    at=classify_log.created_at,
                    detail=f"LLM · {dt} · {conf_text}",
                    state="done",
                )
            )

        if resolved and _on_current_branch(resolved) and (
            gate_fail is None or _is_after(resolved, gate_fail)
        ):
            resolved_detail = resolved.detail if isinstance(resolved.detail, dict) else {}
            dt = str(resolved_detail.get("confirmed_dt") or "—")
            stages.append(
                PipelineStage(
                    stage="Gate",
                    at=resolved.created_at,
                    detail=f"Human confirmed · {dt}",
                    state="done",
                )
            )
        elif gate_log and _on_current_branch(gate_log):
            passed = gate_log.event == "classification_gate_passed"
            detail = gate_log.detail or {}
            conf = detail.get("llm_confidence") or detail.get("confirmed_confidence")
            conf_text = f"{int(float(conf) * 100)}%" if conf is not None else "—"
            stages.append(
                PipelineStage(
                    stage="Gate",
                    at=gate_log.created_at,
                    detail=(
                        f"Auto-route · {conf_text}"
                        if passed
                        else "Awaiting human classification"
                    ),
                    state="done" if passed else "fail",
                )
            )

    return stages


def _vision_path_active(logs: list[AuditLog]) -> bool:
    """True when the latest understand result is can-understand (vision-native hold path)."""
    vu_pass = _latest_log(logs, "vision_understand_passed")
    vu_fail = _latest_log(logs, "vision_understand_failed")
    if vu_pass and vu_fail:
        return _is_after(vu_pass, vu_fail)
    return vu_pass is not None


_VISION_POSTING_CONTINUE_EVENTS = (
    "vision_posting_continued",
    "validation_passed",
    "validation_failed",
    "validation_bypassed_after_human_approval",
    "mapping_applied",
    "invoice_approved",
    "three_way_match_evaluated",
    "match_phase_evaluated",
    "journal_unbalanced",
    "journal_control_account_unresolved",
    "reconciliation_halted",
    "reconciliation_skipped",
    "invoice_processed",
    "invoice_published_to_ledger",
)


def vision_posting_continues(logs: list[AuditLog]) -> bool:
    """True when Understood posting continued past vault (or post-vault work is evident)."""
    if not _vision_path_active(logs):
        return False
    if _latest_log(logs, "vision_posting_continued") is not None:
        return True
    skipped = _latest_log(logs, "vision_posting_skipped")
    if skipped is not None and _latest_log(logs, "vision_posting_continued") is None:
        # Explicit vault-only skip wins unless a later continue event exists (checked above).
        continue_after_skip = _latest_event_log(logs, _VISION_POSTING_CONTINUE_EVENTS)
        if continue_after_skip is None or not _is_after(continue_after_skip, skipped):
            return False
    return _latest_event_log(logs, _VISION_POSTING_CONTINUE_EVENTS) is not None


def _vision_vault_only(inv: Invoice, logs: list[AuditLog]) -> bool:
    """Understood path stopped at vault — post-vault stages should be skipped, not pending."""
    if not _vision_path_active(logs):
        return False
    if vision_posting_continues(logs):
        return False
    if _latest_log(logs, "vision_posting_skipped") is not None:
        return True
    vision_pending_log = _latest_log(logs, "vision_path_pending")
    vu_pass = _latest_log(logs, "vision_understand_passed")
    if (
        vision_pending_log
        and vu_pass
        and _is_after(vision_pending_log, vu_pass)
        and (inv.evaluation_status or "").strip().lower()
        in {"awaiting_classification", "vision_vaulted", "vision_header_review"}
    ):
        return True
    return False


def is_register_supporting_doc(inv: Invoice) -> bool:
    """PO/GRN/SO/DN uploads finish at register sync — commercial Match is not their gate."""
    purchase = (inv.purchase_document_type or "").strip().lower()
    if purchase in {"po", "grn"}:
        return True
    sales = (inv.sales_document_type or "").strip().lower()
    return sales in {"so", "dn"}


def finance_posting_continuum_applies(inv: Invoice) -> bool:
    """Whether Map GL → Journal → Reconcile → Post apply (posting commercials only)."""
    if is_register_supporting_doc(inv):
        return False
    return _gl_posting_applicable(inv)


def _match_audit_stage(inv: Invoice, logs: list[AuditLog]) -> tuple[str, StageState, datetime | None]:
    # Supporting register docs may carry three_way_match_evaluated from sync
    # (audited on the SO/DN/PO/GRN id). That commercial outcome must not mark
    # the supporting upload itself as Match-failed in Upload/Processing.
    if is_register_supporting_doc(inv):
        if inv.status == InvoiceStatus.PROCESSED or _processing_finished(inv, logs):
            terminal = _processing_complete_log(logs)
            return (
                "Not required · supporting document",
                "skipped",
                terminal.created_at if terminal else inv.created_at,
            )
        return ("Not required · supporting document", "skipped", None)

    match_log = _latest_log(logs, "three_way_match_evaluated", "match_phase_evaluated")
    variance_hold = _latest_log(logs, "three_way_match_variance_unapproved")
    variance_ok = _latest_log(logs, "purchase_variance_approved", "sales_variance_approved")
    if variance_hold and (variance_ok is None or _is_after(variance_hold, variance_ok)):
        return (
            "Variance unapproved",
            "fail",
            variance_hold.created_at,
        )
    if match_log:
        detail = match_log.detail if isinstance(match_log.detail, dict) else {}
        match_status = str(detail.get("match_status") or "").strip()
        register = str(detail.get("status") or "").strip()
        status = match_status or register or match_log.event
        if match_status and register.lower() in {
            "",
            "partial",
            "match",
            "mismatch",
            "full_match",
        }:
            status = match_status
        register_l = register.lower()
        failed = register_l == "mismatch" or "fail" in status.lower() or "mismatch" in status.lower()
        if status.lower() in {
            "qty variance",
            "price variance",
            "no dn",
            "no grn",
            "no so",
            "no po",
            "routed for approval",
        }:
            failed = True
        # Finished commercials: register sync may leave a variance audit trail
        # after approval — do not keep Upload Stage stuck on Match.
        if failed and inv.status == InvoiceStatus.PROCESSED:
            return ("Match complete", "done", match_log.created_at)
        return (status or "Match evaluated", "fail" if failed else "done", match_log.created_at)
    if variance_ok:
        return ("Variance approved", "done", variance_ok.created_at)
    if inv.status in (
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
        InvoiceStatus.PROCESSED,
    ):
        return ("Match complete", "done", None)

    # Approval gate held for match without a three_way audit on this invoice
    # (e.g. pre-sync race) — still surface Match as the blocked step.
    approval = _latest_log(logs, "approval_required")
    if approval is not None:
        detail = approval.detail if isinstance(approval.detail, dict) else {}
        if str(detail.get("reason") or "").strip().lower() == "match_not_clean":
            eval_status = (inv.evaluation_status or "").strip().lower()
            if eval_status == "pending_approval" or inv.status == InvoiceStatus.EXCEPTION:
                return ("Routed for approval", "fail", approval.created_at)

    return ("Pending", "pending", None)


def _journal_audit_stage(inv: Invoice, logs: list[AuditLog]) -> tuple[str, StageState, datetime | None]:
    if not finance_posting_continuum_applies(inv):
        return ("Not required · non-posting document", "skipped", None)
    unbalanced = _latest_log(logs, "journal_unbalanced")
    control = _latest_log(logs, "journal_control_account_unresolved")
    if unbalanced and inv.status == InvoiceStatus.EXCEPTION:
        return ("Journal unbalanced", "fail", unbalanced.created_at)
    if control and inv.status == InvoiceStatus.EXCEPTION:
        return ("Control account unresolved", "fail", control.created_at)
    if inv.status in (InvoiceStatus.JOURNALING, InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED):
        processed = _latest_log(logs, "invoice_processed", "purchase_document_processed")
        return ("Balanced journal", "done", processed.created_at if processed else None)
    return ("Pending", "pending", None)


def _reconcile_audit_stage(inv: Invoice, logs: list[AuditLog]) -> tuple[str, StageState, datetime | None]:
    if not finance_posting_continuum_applies(inv):
        return ("Not required · non-posting document", "skipped", None)
    halted = _latest_log(logs, "reconciliation_halted")
    skipped = _latest_log(logs, "reconciliation_skipped")
    if halted and inv.status == InvoiceStatus.EXCEPTION:
        return ("Reconciliation halted", "fail", halted.created_at)
    if skipped or inv.status in (InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED):
        return (
            "Reconcile cleared" if not skipped else "Reconciliation skipped",
            "done",
            skipped.created_at if skipped else None,
        )
    return ("Pending", "pending", None)


def resolve_pipeline_active_path(logs: list[AuditLog]) -> PipelineActivePath:
    """Which Processing sub-tab should be selected by default."""
    vu_pass = _latest_log(logs, "vision_understand_passed")
    vu_fail = _latest_log(logs, "vision_understand_failed")
    if vu_pass and vu_fail:
        return "understood" if _is_after(vu_pass, vu_fail) else "not_understood"
    if vu_pass is not None:
        return "understood"
    if vu_fail is not None:
        return "not_understood"
    return "unknown"


def filter_pipeline_stages_for_path(
    steps: list[PipelineStage],
    path: PipelineActivePath | Literal["understood", "not_understood"],
) -> list[PipelineStage]:
    """Keep only stages that belong to the Understood or Not understood audit tab."""
    if path == "understood":
        allowed = UNDERSTOOD_AUDIT_STAGES
    elif path == "not_understood":
        allowed = NOT_UNDERSTOOD_AUDIT_STAGES
    else:
        return list(steps)
    return [step for step in steps if step.stage in allowed]


def _gl_posting_applicable(inv: Invoice) -> bool:
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )

    return gl_posting_applicable_for_invoice(inv)


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
        and not (inv.document_type_code or "").strip()
        and not (inv.vendor or inv.invoice_no)
        and parsed_log is not None
        and parsed_log.event != "parsing_failed"
    )

    vision_hold = _vision_vault_only(inv, logs)
    vault_only_detail = "Not run · vault-only"

    validation_text, validation_state = _validation_detail(inv, logs)
    if awaiting_reparse:
        validation_text, validation_state = "Pending", "pending"
    if vision_hold:
        # Vault-only Understood path — no tax/totals validation.
        validation_text, validation_state = vault_only_detail, "skipped"
    validated_at = validated_log.created_at if validated_log else None
    if validated_at is None and _stage_index(inv.status) >= 2 and not awaiting_reparse and not vision_hold:
        validated_at = parsed_at or inv.created_at
    if processing_finished and not vision_hold:
        if terminal_log and terminal_log.event == "vault_stored":
            validation_text, validation_state = "Stored in document vault", "done"
        elif terminal_log and terminal_log.event == "purchase_document_processed":
            validation_text, validation_state = "Supporting document processed", "done"
        elif terminal_log and terminal_log.event in {
            "supporting_document_processed",
            "sales_document_processed",
        }:
            validation_text, validation_state = "Reference document processed", "done"
        elif validation_state != "fail":
            validation_text, validation_state = "Passed", "done"
        validated_at = validated_at or (terminal_log.created_at if terminal_log else inv.created_at)

    gl_applicable = _gl_posting_applicable(inv)
    if vision_hold:
        account = vault_only_detail
    elif not gl_applicable:
        account = "Not posted — reference document"
    else:
        account = inv.account_name or ("Pending" if awaiting_reparse else "Suspense Account")
    mapped_at = mapped_log.created_at if mapped_log else None
    if mapped_at is None and gl_applicable and not vision_hold and (
        _stage_index(inv.status) >= 3 and not awaiting_reparse or processing_finished
    ):
        mapped_at = validated_at or inv.created_at
    mapped_suspense = (
        gl_applicable
        and not vision_hold
        and not awaiting_reparse
        and inv.account_name
        and "suspense" in inv.account_name.lower()
    )

    approved_at: datetime | None = None
    approved_detail = "Pending policy"
    approved_state: StageState = "pending"
    if vision_hold:
        approved_detail = vault_only_detail
        approved_state = "skipped"
    elif approved_log:
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
    if vision_hold:
        published_detail = "Not run · vault-only"
        published_state = "skipped"
    elif not finance_posting_continuum_applies(inv):
        published_at = terminal_log.created_at if terminal_log else inv.created_at
        published_detail = f"{doc_ref} · reference only (no ledger post)"
        published_state = "skipped"
    elif is_published_from_audit_logs(logs):
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
            published_state = "pending"
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
        from app.services.audit.audit_change_summary import summarize_audit_change

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
        if vision_hold
        else "pending"
        if awaiting_reparse
        else "done"
        if processing_finished
        else "done"
        if _stage_index(inv.status) >= 1
        else "pending"
    )
    parsed_detail = (
        "Could not read document"
        if parsed_log and parsed_log.event == "parsing_failed"
        else "Vision path · bundled and vaulted"
        if vision_hold
        else "Queued for re-parse"
        if awaiting_reparse
        else f"OCR complete · {parse_conf}% confidence"
        if parse_conf is not None
        else "OCR complete"
        if _stage_index(inv.status) >= 1
        else "Pending"
    )

    mapped_state: StageState = (
        "skipped"
        if vision_hold
        else "skipped"
        if not finance_posting_continuum_applies(inv)
        else "fail"
        if mapped_suspense and inv.status == InvoiceStatus.EXCEPTION and not processing_finished
        else "done"
        if processing_finished or (gl_applicable and _stage_index(inv.status) >= 3)
        else "pending"
    )

    # Understood continue: Validated → Match → Approved → Mapped → Journal → Reconcile → Posted
    # Vault-only / non-posting: skip Match/Journal/Reconcile (and Map/Post when not posting).
    show_post_vault_continuum = _vision_path_active(logs)
    if show_post_vault_continuum and vision_hold:
        match_detail, match_state, match_at = vault_only_detail, "skipped", None
        journal_detail, journal_state, journal_at = vault_only_detail, "skipped", None
        reconcile_detail, reconcile_state, reconcile_at = vault_only_detail, "skipped", None
    elif show_post_vault_continuum:
        match_detail, match_state, match_at = _match_audit_stage(inv, logs)
        journal_detail, journal_state, journal_at = _journal_audit_stage(inv, logs)
        reconcile_detail, reconcile_state, reconcile_at = _reconcile_audit_stage(inv, logs)
    else:
        match_detail = journal_detail = reconcile_detail = ""
        match_state = journal_state = reconcile_state = "pending"
        match_at = journal_at = reconcile_at = None

    stages = [
        PipelineStage(
            stage="Received",
            at=received_at,
            detail=f"{source} · {received_via}",
            state="done",
        ),
    ]
    # Duplicate check sits between receive and storage on both paths.
    if inv.status != InvoiceStatus.DUPLICATE_SKIPPED and (
        _latest_log(logs, "storage_verified") is not None
        or bool((inv.file_hash or "").strip())
        or _latest_log(logs, "vision_understand_passed", "vision_understand_failed") is not None
    ):
        stages.append(
            PipelineStage(
                stage="Duplicate",
                at=received_at,
                detail="File hash unique",
                state="done",
            )
        )
    stages.extend(
        [
            *_early_pipeline_stages(inv, logs),
            PipelineStage(
                stage="Parsed",
                at=parsed_at,
                detail=parsed_detail,
                state=parsed_state,
            ),
        ]
    )

    validated_stage = PipelineStage(
        stage="Validated",
        at=validated_at,
        detail=(
            validation_text
            if vision_hold
            else f"Tax & totals checked · {validation_text}"
        ),
        state=validation_state,
    )
    mapped_stage = PipelineStage(
        stage="Mapped",
        at=mapped_at,
        detail=(account if vision_hold else f"Rule book applied · {account}"),
        state=mapped_state,
    )
    approved_stage = PipelineStage(
        stage="Approved",
        at=approved_at,
        detail=approved_detail,
        state=approved_state,
    )
    posted_stage = PipelineStage(
        stage="Posted",
        at=published_at,
        detail=(published_detail if vision_hold else f"Ledger · {published_detail}"),
        state=published_state,
    )

    # Understood continue: Validated → Match → Approved → Mapped → Journal → Reconcile → Posted
    if show_post_vault_continuum:
        stages.extend(
            [
                validated_stage,
                PipelineStage(
                    stage="Match",
                    at=match_at,
                    detail=match_detail,
                    state=match_state,
                ),
                approved_stage,
                mapped_stage,
                PipelineStage(
                    stage="Journal",
                    at=journal_at,
                    detail=journal_detail,
                    state=journal_state,
                ),
                PipelineStage(
                    stage="Reconcile",
                    at=reconcile_at,
                    detail=reconcile_detail,
                    state=reconcile_state,
                ),
                posted_stage,
            ]
        )
    else:
        stages.extend(
            [
                validated_stage,
                mapped_stage,
                approved_stage,
                posted_stage,
            ]
        )

    dup_log = _latest_log(logs, "duplicate_in_progress", "duplicate_skipped")
    if dup_log is not None:
        from app.services.audit.audit_change_summary import summarize_audit_change

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


def _extracted_fields_if_loaded(inv: Invoice) -> dict:
    """List queries defer extracted_fields — never lazy-load under async SQLAlchemy."""
    try:
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(inv)
        if "extracted_fields" not in state.dict:
            return {}
    except Exception:
        pass
    fields = getattr(inv, "extracted_fields", None)
    return fields if isinstance(fields, dict) else {}


def derive_list_stage(
    inv: Invoice, document_types: list | None = None
) -> tuple[str, StageState]:
    """Fast inbox list label from persisted invoice fields — no audit log scan."""
    status = inv.status
    if status == InvoiceStatus.REJECTED:
        return "Rejected", "fail"
    if status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Duplicate", "skipped"
    if status == InvoiceStatus.PENDING:
        return "Received", "pending"
    if status == InvoiceStatus.PARSING:
        return "Parsed", "pending"
    if status == InvoiceStatus.VALIDATING:
        return "Validated", "pending"
    if status in (
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    ):
        return "Mapped", "pending"
    if status == InvoiceStatus.EXCEPTION:
        eval_status = (inv.evaluation_status or "").strip().lower()
        fields = _extracted_fields_if_loaded(inv)
        has_vision_bundle = bool(
            fields.get("vision_bundle_kind") or fields.get("vision_bundle_key")
        )
        if eval_status == "vision_vaulted" or (
            eval_status == "awaiting_classification" and has_vision_bundle
        ):
            # Understood path finished at vault (incl. legacy soft-bundle rows).
            return "Filed", "done"
        if eval_status == "vision_header_review":
            return "Header review", "pending"
        if eval_status == "awaiting_classification":
            # OCR path — classification gate, not vault.
            return "Parsed", "pending"
        if eval_status in {"awaiting_po", "awaiting_so"}:
            label = "Awaiting PO" if eval_status == "awaiting_po" else "Awaiting SO"
            return label, "pending"
        if eval_status == "pending_approval":
            return "Approved", "pending"
        # Past validate (mapping / recon halt with auto_coded): not a validation fail.
        if (inv.account_code or "").strip() or eval_status == "auto_coded":
            return "Mapped", "fail"
        return "Validated", "fail"
    if status == InvoiceStatus.PROCESSED:
        return "Processed", "done"
    return "Received", "pending"


_RESOLUTION_HINT_BY_EVAL: dict[str, str] = {
    "awaiting_classification": "Fields tab — confirm document type",
    "vision_header_review": "Fields tab — complete header fields, then Confirm & process",
    "vision_vaulted": "Understood path complete — document is vaulted",
    "needs_rescan": "Ask sender for a clearer scan or PDF, then reprocess",
    "pending_vendor": "Creations — register counterparty, then reprocess",
    "awaiting_po": "Purchase register — link or upload the PO, then reprocess",
    "awaiting_so": "Sales register — link or upload the SO / DN, then reprocess",
    "pending_approval": "Approvals board — review and approve this document",
    # needs_review: resolved via field blockers / exception_hold_reason — not a generic drawer hint
}

# Newest matching event wins; order is priority when timestamps tie.
_RESOLUTION_HINT_AUDIT_EVENTS: tuple[tuple[str, str], ...] = (
    ("reconciliation_halted", "Audit tab — reconciliation blocked posting"),
    ("validation_failed", "Audit tab — fix failed validation rules"),
    (
        "journal_control_account_unresolved",
        "Rule Book → Posting — select the missing control ledger from the chart of accounts, then reprocess",
    ),
    ("vendor_registration_hold", "Creations → Vendors — register vendor, then reprocess"),
    ("customer_registration_hold", "Creations → Customers — register customer, then reprocess"),
    ("mapping_review_required", "Lines tab — review GL mapping"),
    ("routing_review_required", "Fields tab — confirm document type / route"),
    ("approval_requested", "Approvals board — waiting for approver sign-off"),
)


def derive_resolution_hint(
    inv: Invoice,
    logs: list[AuditLog] | None = None,
    *,
    configured_keys: list[str] | None = None,
) -> str | None:
    """Actionable next step for Upload / inbox when a document is blocked."""
    from app.services.invoice.invoice_blockers import blocker_fix_hint, detect_invoice_blockers

    status = inv.status
    if status in (InvoiceStatus.PROCESSED, InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED):
        return None
    if status not in (InvoiceStatus.EXCEPTION, InvoiceStatus.PENDING, InvoiceStatus.PARSING):
        # Mid-flight statuses — list already shows pending stage.
        if status in (
            InvoiceStatus.VALIDATING,
            InvoiceStatus.MAPPING,
            InvoiceStatus.JOURNALING,
            InvoiceStatus.RECONCILING,
        ):
            return None

    eval_status = (inv.evaluation_status or "").strip().lower()
    field_hint = blocker_fix_hint(
        detect_invoice_blockers(inv, configured_keys=configured_keys)
    )

    from app.services.invoice.invoice_amounts import invoice_amounts_inconsistent_for_posting
    from app.services.invoice.vision_posting_continue import (
        EXTRACTED_AMOUNT_INCONSISTENCY,
        EXTRACTED_AMOUNT_UNGROUNDED,
        extracted_bool_flag,
    )

    # Must run before eval_overrides: vision_header_review is in that set, so a
    # later branch for it is unreachable. Persist flags (not audit events) so
    # this still works at render time. Skip vaulted DTs — amount holds are for
    # documents that were meant to post.
    # extracted_bool_flag never lazy-loads deferred extracted_fields (matrix
    # list). Inconsistency can also be read from loaded amount columns so
    # Processing cards still distinguish "amounts do not add up".
    # GAP: ungrounded-amount is JSON-only. Unlike inconsistency it cannot be
    # reconstructed from subtotal/gst/total (those values may still be present).
    # List/board therefore falls back to the generic header-incomplete hint until
    # a loaded scalar column exists. Do not treat that fallback as the product
    # intent — see test_deferred_ungrounded_amount_falls_back_to_generic_header_hint.
    if eval_status != "vision_vaulted":
        from app.services.invoice.invoice_data import _attr_if_loaded

        loaded_total = _attr_if_loaded(inv, "total", default=None)
        if extracted_bool_flag(inv, EXTRACTED_AMOUNT_UNGROUNDED) and loaded_total is None:
            return "Fields tab — Amount could not be verified against document text"
        if extracted_bool_flag(inv, EXTRACTED_AMOUNT_INCONSISTENCY) or (
            eval_status == "vision_header_review"
            and invoice_amounts_inconsistent_for_posting(inv)
        ):
            return "Fields tab — Amounts do not add up"

    # Specific eval statuses that are not about missing currency/total.
    eval_overrides = {
        "awaiting_classification",
        "pending_vendor",
        "unmatched_expense_vendor",
        "awaiting_po",
        "awaiting_so",
        "pending_approval",
        "needs_rescan",
        "line_gl_review",
        "line_items_review",
        "vision_vaulted",
        "vision_header_review",
    }
    if eval_status in eval_overrides and eval_status in _RESOLUTION_HINT_BY_EVAL:
        hint = _RESOLUTION_HINT_BY_EVAL[eval_status]
        if eval_status == "pending_vendor":
            route = (inv.route_target or "").strip()
            if route == "Sales Management":
                return "Creations → Customers — register customer, then reprocess"
            return "Creations → Vendors — register vendor, then reprocess"
        return hint

    logs = logs or []
    best: AuditLog | None = None
    best_template = ""
    for event, template in _RESOLUTION_HINT_AUDIT_EVENTS:
        entry = _latest_log(logs, event)
        if entry is None:
            continue
        if best is None or entry.created_at > best.created_at:
            best = entry
            best_template = template
    if best is not None:
        detail = best.detail if isinstance(best.detail, dict) else {}
        reason = str(detail.get("reason") or "").strip()
        if reason and best.event == "reconciliation_halted":
            short = reason if len(reason) <= 120 else reason[:117] + "…"
            return f"{best_template} ({short})"
        if best.event == "journal_control_account_unresolved":
            unresolved = detail.get("unresolved") or []
            if isinstance(unresolved, str):
                unresolved = [unresolved]
            roles = {str(role) for role in unresolved}
            if "staff_advance_account" in roles:
                return (
                    "Rule Book → Posting → Team expense posting — select the "
                    "advance parent ledger from the chart of accounts, then reprocess"
                )
            if "settlement_account" in roles:
                return (
                    "Rule Book → Posting → Team expense posting — select the "
                    "settlement ledger from the chart of accounts, then reprocess"
                )
        return best_template

    # Field blockers beat Suspense / generic needs_review messaging.
    if field_hint:
        return field_hint

    if eval_status == "needs_review":
        account = f"{inv.account_name or ''} {inv.account_code or ''}".lower()
        if "suspense" in account or "unmapped" in account:
            return "Lines tab — assign a GL account or clear suspense mapping"
        return "Fields tab — confirm document type or route"

    if status == InvoiceStatus.EXCEPTION:
        return exception_hold_reason(inv)
    return None


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

    # Terminal processed docs (including supporting register uploads) never stay
    # on Match — sync may have written commercial variance audits onto SO/DN/PO/GRN.
    if inv.status == InvoiceStatus.PROCESSED or (
        _processing_finished(inv, logs) and is_register_supporting_doc(inv)
    ):
        return "Processed", "done"

    if _processing_finished(inv, logs):
        # vault_stored is terminal for vault-only paths.
        # Understood posting continuum still walks Match → Approve → Map after vault.
        match = by_name.get("Match")
        approved = by_name.get("Approved")
        continuum_blocked = match is not None and match.state in ("fail", "pending")
        approval_blocked = (
            match is not None
            and match.state == "done"
            and approved is not None
            and approved.state in ("fail", "pending")
        )
        if not continuum_blocked and not approval_blocked:
            return "Processed", "done"

    last_done: tuple[str, StageState] | None = None
    # Understood posting continuum: Match → Approve → Map.
    # Classic path uses the same finance order via MATRIX_STAGES.
    walk = _INBOX_STAGE_WALK if "Match" in by_name else MATRIX_STAGES
    for name in walk:
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


def _matrix_cell(
    stage: str,
    *,
    state: StageState,
    at: datetime | None = None,
    detail: str = "Pending",
) -> dict[str, str]:
    return {
        "stage": stage,
        "state": state,
        "when": _relative_time(at),
        "detail": detail,
    }


def build_matrix_cells(inv: Invoice, logs: list[AuditLog]) -> list[dict[str, str]]:
    """Matrix grid cells derived from pipeline stages (plain dicts for API schemas)."""
    steps = build_pipeline_stages(inv, logs)
    by_name = {step.stage: step for step in steps}

    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        received = by_name.get("Received")
        dup = by_name.get("Duplicate skipped")
        dup_detail = dup.detail if dup else "Duplicate file skipped"
        cells: list[dict[str, str]] = []
        for stage in MATRIX_STAGES:
            if stage == "Received":
                cells.append(
                    _matrix_cell(
                        stage,
                        state="done",
                        at=received.at if received else inv.created_at,
                        detail=received.detail if received else "Received",
                    )
                )
            elif stage == "Parsed":
                cells.append(
                    _matrix_cell(
                        stage,
                        state="fail",
                        at=dup.at if dup else inv.created_at,
                        detail=dup_detail,
                    )
                )
            else:
                cells.append(
                    _matrix_cell(stage, state="pending", detail="Blocked — duplicate skipped")
                )
        return cells

    if inv.status == InvoiceStatus.REJECTED:
        received = by_name.get("Received")
        rejected = by_name.get("Rejected")
        reject_detail = rejected.detail if rejected else "Document rejected"
        cells = []
        for stage in MATRIX_STAGES:
            if stage == "Received":
                cells.append(
                    _matrix_cell(
                        stage,
                        state="done",
                        at=received.at if received else inv.created_at,
                        detail=received.detail if received else "Received",
                    )
                )
            elif stage == "Parsed":
                cells.append(
                    _matrix_cell(
                        stage,
                        state="fail",
                        at=rejected.at if rejected else inv.created_at,
                        detail=reject_detail,
                    )
                )
            else:
                cells.append(_matrix_cell(stage, state="pending", detail="Blocked — rejected"))
        return cells

    # Fold Match onto Approved in the Summary grid (Match is not a MATRIX column).
    # Only for commercial docs still open — supporting sync audits must not fail Approved.
    match = by_name.get("Match")
    cells = []
    for stage in MATRIX_STAGES:
        step = by_name.get(stage)
        if (
            stage == "Approved"
            and match is not None
            and match.state in ("fail", "pending")
            and not is_register_supporting_doc(inv)
            and inv.status != InvoiceStatus.PROCESSED
        ):
            cells.append(
                _matrix_cell(
                    stage,
                    state=match.state,
                    at=match.at or (step.at if step else None),
                    detail=match.detail,
                )
            )
            continue
        if step:
            cells.append(
                _matrix_cell(
                    stage,
                    state=step.state,
                    at=step.at,
                    detail=step.detail,
                )
            )
            continue
        cells.append(_matrix_cell(stage, state="pending"))

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
