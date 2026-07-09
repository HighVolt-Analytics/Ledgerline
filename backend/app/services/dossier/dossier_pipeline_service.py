"""Build dossier pipeline from invoice state + audit trail.

Stage order mirrors ``process_invoice`` in ``pipeline.py`` and the frontend
``DOSSIER_PIPELINE_STAGES`` catalogue.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.dossier import (
    DossierPipelineCheckResponse,
    DossierPipelineEvidenceResponse,
    DossierPipelineStepResponse,
)
from app.services.audit.audit_change_summary import summarize_audit_change
from app.services.classification.document_type_catalog import ROUTE_SALES
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_VENDOR
from app.services.invoice.pipeline_stages import (
    _actor_name,
    _is_after,
    _latest_log,
    _source_label,
    _validation_results,
)
from app.services.integration.publish_service import is_published_from_audit_logs
from app.services.invoice.processing_cycle_service import latest_cycle_reset_log_id_from_logs

DossierStageState = Literal["pass", "fail", "waived", "pending"]

_VAULT_ROUTE = "vault"


def _is_vault_route(inv: Invoice) -> bool:
    return (inv.route_target or "").strip().lower() == _VAULT_ROUTE


# Approve is listed before map_gl for UI catalogue order; team-expense flows may log
# mapping_applied before approval_requested in the audit trail (see process_invoice).
STAGE_IDS: tuple[str, ...] = (
    "ingest",
    "duplicate",
    "storage",
    "ocr",
    "quality",
    "llm_classify",
    "confidence_gate",
    "extract",
    "document_type",
    "bundle",
    "vendor_hold",
    "validate",
    "match",
    "approve",
    "map_gl",
    "journal",
    "reconcile",
    "post",
    "pay",
    "archive",
)

_STAGE_LABELS = {
    "ingest": "Ingest",
    "duplicate": "Duplicate file check",
    "storage": "Storage",
    "ocr": "OCR",
    "quality": "Image quality",
    "llm_classify": "LLM classify",
    "confidence_gate": "Confidence gate",
    "extract": "Field extract",
    "document_type": "Document type",
    "bundle": "Supporting documents",
    "vendor_hold": "Vendor hold",
    "validate": "Validate",
    "match": "Match",
    "approve": "Approve",
    "map_gl": "Map GL",
    "journal": "Journal",
    "reconcile": "Reconcile",
    "post": "Post",
    "pay": "Pay",
    "archive": "Archive",
}

# Audit events → furthest stage index reached (sync with frontend DOSSIER_PIPELINE_BACKEND_MAP).
_EVENT_STAGE: dict[str, int] = {}
_EVENT_STAGE.update(
    {
        "email_ingested": 0,
        "invoice_uploaded": 0,
        "invoice_file_attached": 0,
        "duplicate_skipped": 1,
        "duplicate_in_progress": 1,
        "duplicate_reingest_rejected": 1,
        "storage_verified": 2,
        "ocr_completed": 3,
        "parsing_failed": 3,
        "image_quality_gate_passed": 4,
        "image_quality_gate_failed": 4,
        "llm_classified": 5,
        "classification_gate_passed": 6,
        "classification_gate_failed": 6,
        "field_confidence_evaluated": 7,
        "parse_completed": 7,
        "invoice_parsed": 7,
        "document_classified": 8,
        "classification_resolved": 8,
        "playbook_evaluated": 9,
        "vendor_registration_hold": 10,
        "vendor_registration_cleared": 10,
        "vendor_registration_waived": 10,
        "vendor_registration_released": 10,
        "validation_passed": 11,
        "validation_failed": 11,
        "validation_bypassed_after_human_approval": 11,
        "routing_review_required": 11,
        "three_way_match_evaluated": 12,
        "match_phase_evaluated": 12,
        "match_context_incomplete": 12,
        "purchase_variance_approved": 12,
        "sales_variance_approved": 12,
        "variance_approval_reprocess_queued": 12,
        "variance_approval_posting_resumed": 15,
        "three_way_match_variance_unapproved": 15,
        "invoice_approved": 13,
        "approval_required": 13,
        "approval_requested": 13,
        "team_expense_approval_required": 13,
        "mapping_applied": 14,
        "mapping_review_required": 14,
        "journal_unbalanced": 15,
        "journal_control_account_unresolved": 15,
        "reconciliation_halted": 16,
        "reconciliation_skipped": 16,
        "invoice_processed": 17,
        "invoice_published_to_ledger": 17,
        "purchase_document_processed": 17,
        "vault_stored": 19,
    }
)

_STATUS_FLOOR: dict[InvoiceStatus, int] = {
    InvoiceStatus.PENDING: 0,
    InvoiceStatus.PARSING: 7,
    InvoiceStatus.VALIDATING: 11,
    InvoiceStatus.MAPPING: 14,
    InvoiceStatus.JOURNALING: 15,
    InvoiceStatus.RECONCILING: 16,
    InvoiceStatus.PROCESSED: 17,
    InvoiceStatus.DUPLICATE_SKIPPED: 1,
    InvoiceStatus.REJECTED: 0,
}

_REMEDIATION: dict[str, str] = {
    "DUPLICATE_FILE": "Use the existing dossier or request a controlled re-ingest if the prior file was wrong.",
    "PARSE_FAILED": "Re-upload a readable PDF or fix the stored file path, then reprocess.",
    "IMAGE_QUALITY": "Resend a flat, well-lit scan or PDF — avoid angled phone photos.",
    "CLASSIFICATION_GATE": "Confirm document type in the exception queue or adjust rule-book classifiers.",
    "BUNDLE_INCOMPLETE": "Upload the missing mandatory bundle documents on the same linkage key.",
    "LINKAGE_KEY_MISSING": "Extract or enter a valid PO number, then link PO and GRN supporting documents on that PO.",
    "LINKAGE_KEY_MISSING_SALES": "Extract or enter a valid SO number, then link SO and delivery note supporting documents on that SO.",
    "EXTRACTION_INCOMPLETE": "Capture or correct required invoice fields before posting.",
    "VENDOR_HOLD": "Approve the vendor in Vendor Masters or clear the registration hold.",
    "VENDOR_HOLD_SALES": "Approve the customer in Customer Masters or clear the registration hold.",
    "VALIDATION_FAILED": "Correct the document or override failed validation rules in the exception queue.",
    "ROUTING_REVIEW": "Confirm document type classification or adjust rule-book routing.",
    "DOCUMENT_UNCLASSIFIED": "Classify the document type in Rule Book or reclassify from the exception queue.",
    "MATCH_FAILED": "Link PO/GRN, approve variance, or update purchase register lines.",
    "MATCH_FAILED_SALES": "Link SO/DN, approve variance, or update sales register lines.",
    "APPROVAL_REQUIRED": "Route to the approver named in the playbook policy.",
    "MAP_SUSPENSE": "Map to a real GL account in the rule book or approve suspense mapping.",
    "MAP_CONFIG": "Set Post to ledger for this document type in Rule Book → Document types.",
    "JOURNAL_UNBALANCED": "Correct subtotal, GST, and total on the invoice or reprocess after extraction fixes.",
    "JOURNAL_CONTROL_ACCOUNT_UNRESOLVED": (
        "Add the missing payable, receivable, or tax account names to Chart of Accounts "
        "(Settings → Rule Book), then reprocess."
    ),
    "PIPELINE_ERROR": "Fix the reported issue and reprocess the dossier from the exception queue.",
    "RECON_HALTED": "Clear the daily reconciliation halt before posting.",
    "PAY_FAILED": "Review payment details and re-release from the payments queue.",
}

_PIPELINE_ERROR_SUPERSEDED_BY = frozenset(
    {
        "storage_verified",
        "parse_completed",
        "invoice_parsed",
        "validation_passed",
        "mapping_applied",
        "invoice_processed",
        "invoice_published_to_ledger",
    }
)


def _fmt_at(at: datetime | None) -> str | None:
    if at is None:
        return None
    return at.strftime("%Y-%m-%d %H:%M:%S")


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _detail_from_log(log: AuditLog | None, *, fallback: str = "—") -> str:
    if log is None:
        return fallback
    detail = log.detail if isinstance(log.detail, dict) else {}
    summary = summarize_audit_change(log.event, detail)
    return summary or fallback


def _cycle_logs(logs: list[AuditLog]) -> list[AuditLog]:
    """Audit entries from the current processing cycle (after last requeue/reject)."""
    reset_id = latest_cycle_reset_log_id_from_logs(logs)
    if reset_id <= 0:
        return logs
    return [entry for entry in logs if entry.id > reset_id]


def _watermark(logs: list[AuditLog], inv: Invoice) -> int:
    wm = _STATUS_FLOOR.get(inv.status, -1)
    for entry in logs:
        idx = _EVENT_STAGE.get(entry.event)
        if idx is not None:
            wm = max(wm, idx)
    if inv.status == InvoiceStatus.EXCEPTION:
        # Exception can stop anywhere — trust audit trail, not status floor.
        wm = max((_EVENT_STAGE.get(e.event, -1) for e in logs), default=-1)
    return wm


def _map_gl_complete(inv: Invoice, logs: list[AuditLog]) -> bool:
    if _is_vault_route(inv):
        return True
    return bool(_latest_log(logs, "mapping_applied") or (inv.account_name or "").strip())


def _routing_review_fail_for_stage(
    logs: list[AuditLog],
    inv: Invoice,
    *,
    gate: str,
    stage_id: str,
    exception_code: str,
    remediation: str,
    require_exception: bool = True,
) -> DossierPipelineStepResponse | None:
    """Fail a stage when routing_review_required blocks on a specific gate."""
    if require_exception and inv.status != InvoiceStatus.EXCEPTION:
        return None
    routing = _latest_log(logs, "routing_review_required")
    if routing is None or _routing_review_gate(routing) != gate:
        return None
    resolved = _latest_log(logs, "classification_resolved")
    if resolved and _is_after(resolved, routing):
        return None
    validate_pass = _latest_log(logs, "validation_passed")
    if validate_pass and _is_after(validate_pass, routing):
        return None
    gate_pass = _latest_log(logs, "classification_gate_passed")
    if gate == "classification" and gate_pass and _is_after(gate_pass, routing):
        return None
    quality_pass = _latest_log(logs, "image_quality_gate_passed")
    if gate == "image_quality" and quality_pass and _is_after(quality_pass, routing):
        return None
    reason = _detail_from_log(routing, fallback="routing_review_required")
    detail_dict = _routing_review_detail(routing)
    reason_labels = _format_review_reasons(detail_dict.get("review_reasons"))
    failure = reason_labels or reason
    return _step(
        stage_id,
        state="fail",
        detail=failure,
        at=routing.created_at,
        exception_code=exception_code,
        failure_reason=failure,
        remediation=remediation,
    )


def _validation_checks(
    inv: Invoice,
    document_types: list | None = None,
) -> list[DossierPipelineCheckResponse]:
    from app.services.rule_book.validation_rule_catalog import effective_validation_rules, enabled_rule_codes
    from app.services.master_data.vendor_registration_policy import resolve_document_type_definition

    allowed: set[str] | None = None
    if document_types:
        definition = resolve_document_type_definition(
            inv.document_type_code,
            document_types=document_types,
        )
        if definition is not None:
            allowed = enabled_rule_codes(effective_validation_rules(definition)) | {"VR02"}

    checks: list[DossierPipelineCheckResponse] = []
    for row in _validation_results(inv):
        rule = str(row.get("rule", "")).strip() or "rule"
        if (
            allowed is not None
            and rule not in allowed
            and not rule.startswith("VR-TE")
        ):
            continue
        passed = bool(row.get("passed"))
        skipped = bool(row.get("skipped"))
        state: str = "skipped" if skipped else "pass" if passed else "fail"
        message = str(row.get("message", rule)).strip() or rule
        checks.append(
            DossierPipelineCheckResponse(
                id=rule.lower(),
                label=message,
                state=state,
                rule_ref=rule,
                detail=None if passed or skipped else message,
            )
        )
    return checks


def _playbook_detail_dict(detail_dict: dict[str, object]) -> dict[str, object]:
    nested = detail_dict.get("playbook")
    if isinstance(nested, dict):
        merged = {**nested, **{k: v for k, v in detail_dict.items() if k != "playbook"}}
        return merged
    return detail_dict


def _bundle_checks(detail: dict[str, object]) -> list[DossierPipelineCheckResponse]:
    checks: list[DossierPipelineCheckResponse] = []
    merged = _playbook_detail_dict(detail)
    book = str(merged.get("linkage_book") or "purchase").strip().lower()
    ref_label = "SO" if book == "sales" else "PO"
    labels = merged.get("missing_bundle_mandatory_labels")
    label_map = labels if isinstance(labels, dict) else {}
    missing = merged.get("missing_bundle_mandatory") or []
    if isinstance(missing, list):
        for code in missing:
            token = str(code).strip().upper()
            if not token:
                continue
            title = str(label_map.get(token) or label_map.get(str(code)) or token)
            checks.append(
                DossierPipelineCheckResponse(
                    id=f"bundle-{token.lower()}",
                    label=f"Required: {title}",
                    state="fail",
                    rule_ref="VR-PB02",
                    detail=f"{title} ({token}) not on file for this {ref_label}",
                )
            )
    missing_fields = merged.get("missing_extraction_fields") or []
    if isinstance(missing_fields, list):
        for field in missing_fields:
            token = str(field).strip()
            if not token:
                continue
            checks.append(
                DossierPipelineCheckResponse(
                    id=f"extract-{token}",
                    label=f"Required field: {token}",
                    state="fail",
                    rule_ref="VR03",
                    detail=f"{token} not captured",
                )
            )
    if merged.get("linkage_key_missing"):
        checks.insert(
            0,
            DossierPipelineCheckResponse(
                id=f"linkage-{ref_label.lower()}",
                label=f"{ref_label} reference",
                state="fail",
                rule_ref="VR-PB02",
                detail=f"Valid {ref_label} reference required to link supporting documents",
            ),
        )
    if not checks and not merged.get("has_validation_gaps"):
        checks.append(
            DossierPipelineCheckResponse(
                id="bundle-ok",
                label="Supporting documents satisfied",
                state="pass",
                rule_ref="VR-PB02",
            )
        )
    return checks


def _mapping_checks(detail: dict[str, object], account: str) -> list[DossierPipelineCheckResponse]:
    rule_type = str(detail.get("rule_type") or "").strip()
    match_reason = str(detail.get("match_reason") or "").strip()
    checks = [
        DossierPipelineCheckResponse(
            id="gl-rule",
            label="Purchase rule matched" if rule_type else "GL mapping applied",
            state="pass",
            rule_ref=rule_type or "mapping_applied",
            detail=match_reason or None,
        ),
        DossierPipelineCheckResponse(
            id="gl-acct",
            label="GL account resolved",
            state="pass" if account and "suspense" not in account.lower() else "fail",
            rule_ref="mapping_applied",
            expected="Not suspense",
            actual=account or "—",
        ),
    ]
    return checks


def _routing_review_detail(log: AuditLog | None) -> dict[str, object]:
    if log is None or not isinstance(log.detail, dict):
        return {}
    return log.detail


def _routing_review_gate(log: AuditLog | None) -> str:
    return str(_routing_review_detail(log).get("gate") or "").strip().lower()


_REVIEW_REASON_LABELS: dict[str, str] = {
    "LLM_LOW_CONF": "LLM confidence below auto-route threshold",
    "CLASSIFIER_RULE_MISMATCH": "Custom classifier rules do not match document text",
    "DT_NOT_IN_CATALOGUE": "Suggested type is not in your Rule Book",
    "DT_DISABLED": "Suggested document type is disabled",
    "LLM_INVALID": "Classification model returned no usable result",
    "OCR_SPARSE": "OCR text is too sparse",
    "IMAGE_QUALITY_LOW": "Scan or image quality is too poor",
    "DT_MISMATCH": "LLM and policy classifiers disagree",
    "POLICY_LOW_CONF": "Policy classifier confidence is too low",
    "PERSPECTIVE_AMBIGUOUS": "Could not determine purchase vs sales perspective",
    "EXTRACTION_GAP": "Required fields missing for suggested document type",
    "NEVER_AUTO_POLICY": "Document type is configured to always require review",
    "PROVIDER_UNAVAILABLE": "Document AI provider unavailable",
    "VENDOR_CLASSIFICATION_DRIFT": "Vendor classification differs from recent history",
    "FIELD_CONFIDENCE_LOW": "Extracted field confidence is too low",
}


def _format_review_reasons(reasons: object) -> str:
    if not isinstance(reasons, list) or not reasons:
        return ""
    labels: list[str] = []
    for raw in reasons:
        token = str(raw).strip()
        if not token:
            continue
        labels.append(_REVIEW_REASON_LABELS.get(token, token.replace("_", " ").lower()))
    return "; ".join(labels)


def _latest_classification_gate_log(logs: list[AuditLog]) -> AuditLog | None:
    gate_pass = _latest_log(logs, "classification_gate_passed")
    gate_fail = _latest_log(logs, "classification_gate_failed")
    if gate_pass and gate_fail:
        return gate_pass if _is_after(gate_pass, gate_fail) else gate_fail
    return gate_pass or gate_fail


def _looks_like_non_classification_routing(detail: dict[str, object]) -> bool:
    gate = str(detail.get("gate") or "").strip().lower()
    if gate in ("image_quality", "field_confidence", "vendor_classification_drift", "playbook"):
        return True
    if gate:
        return False
    if detail.get("low_confidence_fields"):
        return True
    if detail.get("sparse") is not None or detail.get("text_length") is not None:
        return True
    return False


def classification_review_pending(logs: list[AuditLog]) -> bool:
    """True when classify stage is blocked pending human DT confirmation."""
    return _classification_routing_review(logs) is not None


def _classification_routing_review(logs: list[AuditLog]) -> AuditLog | None:
    routing = _latest_log(logs, "routing_review_required")
    if routing is None:
        return None
    resolved = _latest_log(logs, "classification_resolved")
    if resolved and resolved.created_at >= routing.created_at:
        return None
    validate_pass = _latest_log(logs, "validation_passed")
    if validate_pass and validate_pass.created_at > routing.created_at:
        return None
    gate_log = _latest_classification_gate_log(logs)
    if (
        gate_log is not None
        and gate_log.event == "classification_gate_passed"
        and _is_after(gate_log, routing)
    ):
        return None
    gate = _routing_review_gate(routing)
    detail = _routing_review_detail(routing)
    if gate == "classification":
        return routing
    if gate == "playbook":
        return None
    if detail.get("no_classifier_match"):
        return routing
    if gate == "" and validate_pass is None and not _looks_like_non_classification_routing(detail):
        return routing
    return None


def _playbook_routing_review(logs: list[AuditLog]) -> AuditLog | None:
    routing = _latest_log(logs, "routing_review_required")
    if routing is None:
        return None
    if _routing_review_gate(routing) != "playbook":
        return None
    validate_pass = _latest_log(logs, "validation_passed")
    if validate_pass and validate_pass.created_at > routing.created_at:
        return None
    return routing


def _is_sales_route(inv: Invoice) -> bool:
    return (inv.route_target or "").strip() == ROUTE_SALES


def _remediation_for(
    code: str | None,
    inv: Invoice,
    fallback: str | None = None,
) -> str | None:
    if not code:
        return fallback
    if _is_sales_route(inv):
        sales_key = f"{code}_SALES"
        if sales_key in _REMEDIATION:
            return _REMEDIATION[sales_key]
    return _REMEDIATION.get(code, fallback)


def _confidence_label(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    pct = int(round(num * 100)) if num <= 1 else int(round(num))
    return f"{pct}%"


def _step(
    stage_id: str,
    *,
    state: DossierStageState,
    detail: str,
    at: datetime | None = None,
    actor: str | None = None,
    exception_code: str | None = None,
    failure_reason: str | None = None,
    remediation: str | None = None,
    checks: list[DossierPipelineCheckResponse] | None = None,
    evidence: list[DossierPipelineEvidenceResponse] | None = None,
) -> DossierPipelineStepResponse:
    return DossierPipelineStepResponse(
        stage_id=stage_id,
        state=state,
        detail=detail,
        at=_fmt_at(at),
        actor=actor,
        exception_code=exception_code,
        failure_reason=failure_reason,
        remediation=remediation,
        checks=checks or [],
        evidence=evidence or [],
    )


def _resolve_ingest(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    log = _latest_log(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached")
    if log:
        return _step(
            "ingest",
            state="pass",
            detail=_detail_from_log(log, fallback=f"{_source_label(inv)} captured"),
            at=log.created_at,
            actor=_actor_name(log.detail if isinstance(log.detail, dict) else None),
        )
    if inv.created_at or wm >= 0:
        return _step(
            "ingest",
            state="pass",
            detail=f"{_source_label(inv)} · captured",
            at=inv.created_at,
        )
    return _step("ingest", state="pending", detail="—")


def _duplicate_pass_step(inv: Invoice, logs: list[AuditLog]) -> DossierPipelineStepResponse:
    ingest_log = _latest_log(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached")
    return _step(
        "duplicate",
        state="pass",
        detail="File hash unique",
        at=ingest_log.created_at if ingest_log else inv.created_at,
    )


def _resolve_duplicate(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    dup_log = _latest_log(
        logs, "duplicate_skipped", "duplicate_in_progress", "duplicate_reingest_rejected"
    )
    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
        reason = _detail_from_log(dup_log, fallback="Duplicate file skipped")
        return _step(
            "duplicate",
            state="fail",
            detail=reason,
            at=dup_log.created_at if dup_log else inv.created_at,
            exception_code="DUPLICATE_FILE",
            failure_reason=reason,
            remediation=_REMEDIATION["DUPLICATE_FILE"],
        )
    if dup_log and dup_log.event == "duplicate_in_progress":
        # Logged on the canonical row when a concurrent re-submit was blocked — not a failure.
        if wm >= 2:
            return _duplicate_pass_step(inv, logs)
        return _step(
            "duplicate",
            state="pending",
            detail=_detail_from_log(dup_log),
            at=dup_log.created_at,
        )
    if dup_log and dup_log.event in {"duplicate_skipped", "duplicate_reingest_rejected"}:
        # Informational repeat-submission or controlled re-ingest on the canonical row.
        return _duplicate_pass_step(inv, logs)
    if wm >= 2:
        return _duplicate_pass_step(inv, logs)
    # Canonical row already stored — duplicate was cleared at ingest even if this cycle
    # has no storage_verified yet (e.g. after requeue or early pipeline_error).
    if (inv.file_hash or "").strip():
        return _duplicate_pass_step(inv, logs)
    return _step("duplicate", state="pending", detail="—")


def _fail_reason(log: AuditLog | None) -> str:
    if log is None or not isinstance(log.detail, dict):
        return ""
    return str(log.detail.get("reason") or "").strip().lower()


def _legacy_capture_complete(logs: list[AuditLog], wm: int) -> bool:
    return wm >= 7 or _latest_log(logs, "parse_completed", "invoice_parsed") is not None


def _provider_detail(log: AuditLog | None) -> str:
    if log and isinstance(log.detail, dict):
        provider = log.detail.get("document_ai_provider") or log.detail.get("source")
        if provider:
            return str(provider)
    return "Document AI"


def _resolve_storage(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    storage_log = _latest_log(logs, "storage_verified")
    parse_completed = _latest_log(logs, "parse_completed", "invoice_parsed")
    parse_failed = _latest_log(logs, "parsing_failed")
    if parse_failed and _fail_reason(parse_failed) in {"stored_file_missing", "no_stored_path"}:
        stale_failure = parse_completed and (
            parse_completed.created_at >= parse_failed.created_at
            or bool(inv.vendor or inv.invoice_no or (inv.document_type_code or "").strip())
        )
        if not stale_failure and (
            storage_log is None or parse_failed.created_at >= storage_log.created_at
        ):
            reason = _detail_from_log(parse_failed, fallback="Stored file missing")
            return _step(
                "storage",
                state="fail",
                detail=reason,
                at=parse_failed.created_at,
                exception_code="PARSE_FAILED",
                failure_reason=reason,
                remediation=_REMEDIATION["PARSE_FAILED"],
            )
    if storage_log:
        return _step(
            "storage",
            state="pass",
            detail=_detail_from_log(storage_log, fallback="storage_verified"),
            at=storage_log.created_at,
        )
    if _legacy_capture_complete(logs, wm):
        return _step("storage", state="pass", detail="storage_verified · legacy run")
    # File persisted at ingest — cycle reset drops storage_verified from the audit view.
    from app.services.shared.file_storage import has_stored_path

    if (inv.file_hash or "").strip() and has_stored_path(inv.raw_file_path):
        ingest_log = _latest_log(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached")
        return _step(
            "storage",
            state="pass",
            detail="Stored file on record",
            at=ingest_log.created_at if ingest_log else inv.created_at,
        )
    return _step("storage", state="pending", detail="—")


def _resolve_ocr(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    ocr_log = _latest_log(logs, "ocr_completed")
    parse_completed = _latest_log(logs, "parse_completed", "invoice_parsed")
    parse_failed = _latest_log(logs, "parsing_failed")

    if parse_failed:
        reason_key = _fail_reason(parse_failed)
        stale_failure = parse_completed and (
            parse_completed.created_at >= parse_failed.created_at
            or bool(inv.vendor or inv.invoice_no or (inv.document_type_code or "").strip())
        )
        if not stale_failure and reason_key in {"ocr_failed", "stored_file_missing", "no_stored_path"}:
            reason = _detail_from_log(parse_failed, fallback="OCR failed")
            return _step(
                "ocr",
                state="fail",
                detail=reason,
                at=parse_failed.created_at,
                exception_code="PARSE_FAILED",
                failure_reason=reason,
                remediation=_REMEDIATION["PARSE_FAILED"],
            )

    if ocr_log:
        detail_dict = ocr_log.detail if isinstance(ocr_log.detail, dict) else {}
        conf = detail_dict.get("confidence", "high")
        text_len = detail_dict.get("text_length")
        detail = _detail_from_log(ocr_log, fallback="ocr_completed")
        if text_len is not None:
            detail = f"{detail} · {text_len} chars"
        elif conf:
            detail = f"{detail} · {conf} confidence"
        return _step(
            "ocr",
            state="pass",
            detail=detail,
            at=ocr_log.created_at,
            actor=_actor_name(detail_dict),
        )
    if parse_completed or _legacy_capture_complete(logs, wm):
        return _step("ocr", state="pass", detail="ocr_completed · legacy run")
    return _step("ocr", state="pending", detail="—")


def _resolve_quality(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    routing_fail = _routing_review_fail_for_stage(
        logs,
        inv,
        gate="image_quality",
        stage_id="quality",
        exception_code="IMAGE_QUALITY",
        remediation=_REMEDIATION["IMAGE_QUALITY"],
    )
    if routing_fail is not None:
        return routing_fail

    quality_pass = _latest_log(logs, "image_quality_gate_passed")
    quality_fail = _latest_log(logs, "image_quality_gate_failed")
    quality_log = quality_pass or quality_fail
    if quality_log:
        passed = quality_log.event == "image_quality_gate_passed"
        detail_dict = quality_log.detail if isinstance(quality_log.detail, dict) else {}
        text_len = detail_dict.get("text_length")
        detail = _detail_from_log(
            quality_log,
            fallback="Image quality OK" if passed else "Poor image or sparse OCR",
        )
        if passed and text_len is not None:
            detail = f"OCR readable · {text_len} chars"
        if not passed:
            return _step(
                "quality",
                state="fail",
                detail=detail,
                at=quality_log.created_at,
                exception_code="IMAGE_QUALITY",
                failure_reason=detail,
                remediation=_REMEDIATION["IMAGE_QUALITY"],
            )
        return _step("quality", state="pass", detail=detail, at=quality_log.created_at)
    if _legacy_capture_complete(logs, wm):
        return _step("quality", state="pass", detail="image_quality_gate_passed · legacy run")
    return _step("quality", state="pending", detail="—")


def _resolve_llm_classify(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    routing_fail = _routing_review_fail_for_stage(
        logs,
        inv,
        gate="vendor_classification_drift",
        stage_id="llm_classify",
        exception_code="CLASSIFICATION_GATE",
        remediation=_REMEDIATION["CLASSIFICATION_GATE"],
        require_exception=False,
    )
    if routing_fail is not None:
        return routing_fail

    classify_log = _latest_log(logs, "llm_classified")
    if classify_log:
        detail_dict = classify_log.detail if isinstance(classify_log.detail, dict) else {}
        dt = detail_dict.get("llm_suggested_dt") or inv.llm_suggested_dt or "—"
        conf = _confidence_label(detail_dict.get("llm_confidence") or inv.llm_confidence)
        detail = _detail_from_log(classify_log, fallback=f"llm_classified · {dt}")
        if conf:
            detail = f"{detail} · {conf}"
        return _step("llm_classify", state="pass", detail=detail, at=classify_log.created_at)
    if inv.llm_suggested_dt and wm >= 5:
        conf = _confidence_label(inv.llm_confidence)
        detail = f"llm_classified · {inv.llm_suggested_dt}"
        if conf:
            detail = f"{detail} · {conf}"
        return _step("llm_classify", state="pass", detail=detail)
    gate_pass = _latest_log(logs, "classification_gate_passed")
    document_classified = _latest_log(logs, "document_classified")
    classification_resolved = _latest_log(logs, "classification_resolved")
    if gate_pass or document_classified or classification_resolved:
        dt = (
            (inv.document_type_code or inv.llm_suggested_dt or "—").strip()
            or "—"
        )
        at = (
            (gate_pass or document_classified or classification_resolved).created_at
            if (gate_pass or document_classified or classification_resolved)
            else None
        )
        return _step("llm_classify", state="pass", detail=f"llm_classified · {dt} · skipped", at=at)
    if _legacy_capture_complete(logs, wm) and (inv.document_type_code or inv.llm_suggested_dt):
        return _step("llm_classify", state="pass", detail="llm_classified · legacy run")
    return _step("llm_classify", state="pending", detail="—")


def _resolve_confidence_gate(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    gate_pass = _latest_log(logs, "classification_gate_passed")
    gate_fail = _latest_log(logs, "classification_gate_failed")
    classification_review = _classification_routing_review(logs)
    resolved = _latest_log(logs, "classification_resolved")

    if classification_review:
        detail = _detail_from_log(classification_review, fallback="Awaiting human classification")
        detail_dict = _routing_review_detail(classification_review)
        reason_labels = _format_review_reasons(detail_dict.get("review_reasons"))
        reason = reason_labels or str(detail_dict.get("reason") or detail).strip() or "Awaiting human classification"
        return _step(
            "confidence_gate",
            state="fail",
            detail=reason,
            at=classification_review.created_at,
            exception_code="DOCUMENT_UNCLASSIFIED",
            failure_reason=reason,
            remediation=_REMEDIATION["DOCUMENT_UNCLASSIFIED"],
        )

    if resolved and (gate_fail is None or _is_after(resolved, gate_fail)):
        detail_dict = resolved.detail if isinstance(resolved.detail, dict) else {}
        dt = str(detail_dict.get("confirmed_dt") or inv.document_type_code or "—").strip() or "—"
        return _step(
            "confidence_gate",
            state="pass",
            detail=f"Human confirmed · {dt}",
            at=resolved.created_at,
        )

    gate_log: AuditLog | None
    if gate_pass and gate_fail:
        gate_log = gate_pass if _is_after(gate_pass, gate_fail) else gate_fail
    else:
        gate_log = gate_pass or gate_fail

    if gate_log:
        passed = gate_log.event == "classification_gate_passed"
        detail_dict = gate_log.detail if isinstance(gate_log.detail, dict) else {}
        conf = _confidence_label(detail_dict.get("llm_confidence") or detail_dict.get("confirmed_confidence"))
        detail = _detail_from_log(
            gate_log,
            fallback="classification_gate_passed" if passed else "classification_gate_failed",
        )
        if passed and conf:
            detail = f"Auto-route · {conf}"
        if not passed:
            reasons = detail_dict.get("review_reasons") or []
            failure = _format_review_reasons(reasons) or detail
            return _step(
                "confidence_gate",
                state="fail",
                detail=failure,
                at=gate_log.created_at,
                exception_code="CLASSIFICATION_GATE",
                failure_reason=failure,
                remediation=_REMEDIATION["CLASSIFICATION_GATE"],
            )
        return _step("confidence_gate", state="pass", detail=detail, at=gate_log.created_at)

    if _legacy_capture_complete(logs, wm):
        return _step("confidence_gate", state="pass", detail="classification_gate_passed · legacy run")
    return _step("confidence_gate", state="pending", detail="—")


def _resolve_document_type(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    classify_log = _latest_log(logs, "document_classified")
    code = (inv.document_type_code or "").strip()
    if classify_log:
        detail = _detail_from_log(
            classify_log,
            fallback=f"document_classified · {code}" if code else "document_classified",
        )
        return _step("document_type", state="pass", detail=detail, at=classify_log.created_at)
    if code and wm >= 8:
        conf = _confidence_label(inv.document_type_confidence)
        detail = f"document_classified · {code}"
        if conf:
            detail = f"{detail} · conf {conf}"
        return _step("document_type", state="pass", detail=detail)
    return _step("document_type", state="pending", detail="—")


def _resolve_extract(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    routing_fail = _routing_review_fail_for_stage(
        logs,
        inv,
        gate="field_confidence",
        stage_id="extract",
        exception_code="EXTRACTION_INCOMPLETE",
        remediation=_REMEDIATION["EXTRACTION_INCOMPLETE"],
        require_exception=False,
    )
    if routing_fail is not None:
        return routing_fail

    parse_completed = _latest_log(logs, "parse_completed", "invoice_parsed")
    parse_failed = _latest_log(logs, "parsing_failed")
    parse_log = parse_completed
    if parse_failed and parse_completed:
        if parse_completed.created_at >= parse_failed.created_at:
            parse_log = parse_completed
        elif (inv.vendor or inv.invoice_no or (inv.document_type_code or "").strip()):
            parse_log = parse_completed
        else:
            parse_log = parse_failed
    elif parse_failed and not parse_completed:
        parse_log = parse_failed

    if parse_log and parse_log.event == "parsing_failed":
        reason_key = _fail_reason(parse_log)
        if reason_key not in {"ocr_failed", "stored_file_missing", "no_stored_path"}:
            reason = _detail_from_log(parse_log, fallback="Could not extract fields")
            return _step(
                "extract",
                state="fail",
                detail=reason,
                at=parse_log.created_at,
                exception_code="PARSE_FAILED",
                failure_reason=reason,
                remediation=_REMEDIATION["PARSE_FAILED"],
            )

    if parse_log and parse_log.event != "parsing_failed":
        detail_dict = parse_log.detail if isinstance(parse_log.detail, dict) else {}
        conf = _confidence_label(detail_dict.get("confidence"))
        detail = _detail_from_log(parse_log, fallback="parse_completed")
        if conf:
            detail = f"{detail} · {conf} confidence"
        return _step(
            "extract",
            state="pass",
            detail=detail,
            at=parse_log.created_at,
            actor=_actor_name(detail_dict),
        )
    if wm >= 8 and (inv.vendor or inv.invoice_no):
        return _step(
            "extract",
            state="pass",
            detail="Fields extracted",
            at=inv.created_at,
        )
    return _step("extract", state="pending", detail="—")


def _resolve_classify(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    """Legacy alias — kept for imports; maps to document_type."""
    return _resolve_document_type(inv, logs, wm)


def _resolve_bundle(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    bundle_log = _latest_log(logs, "playbook_evaluated")
    if bundle_log:
        detail_dict = bundle_log.detail if isinstance(bundle_log.detail, dict) else {}
        merged = _playbook_detail_dict(detail_dict)
        detail = _detail_from_log(bundle_log, fallback="playbook_evaluated")
        checks = _bundle_checks(merged)
        return _step(
            "bundle",
            state="pass",
            detail=detail,
            at=bundle_log.created_at,
            checks=checks,
        )
    if wm >= 9:
        return _step("bundle", state="pass", detail="playbook_evaluated")
    return _step("bundle", state="pending", detail="—")


def _resolve_vendor_hold(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    is_sales = (inv.route_target or "").strip() == ROUTE_SALES
    hold_event = "customer_registration_hold" if is_sales else "vendor_registration_hold"
    cleared_events = (
        ("customer_registration_cleared",)
        if is_sales
        else ("vendor_registration_cleared", "vendor_registration_released")
    )
    waived_event = "customer_registration_waived" if is_sales else "vendor_registration_waived"

    hold_log = _latest_log(logs, hold_event)
    cleared_log = _latest_log(logs, *cleared_events)
    waived_log = _latest_log(logs, waived_event)
    validate_pass = _latest_log(logs, "validation_passed")

    if waived_log and (hold_log is None or _is_after(waived_log, hold_log)):
        reason = _detail_from_log(waived_log, fallback=waived_event)
        return _step(
            "vendor_hold",
            state="waived",
            detail=reason,
            at=waived_log.created_at,
        )

    if cleared_log and (hold_log is None or _is_after(cleared_log, hold_log)):
        reason = _detail_from_log(cleared_log, fallback=cleared_events[0])
        return _step(
            "vendor_hold",
            state="pass",
            detail=reason,
            at=cleared_log.created_at,
        )

    if inv.evaluation_status == EVAL_PENDING_VENDOR:
        reason = (
            "Customer not registered — pending customer registration"
            if is_sales
            else "Vendor not registered — pending vendor registration"
        )
        hold_at = hold_log.created_at if hold_log else None
        exception_code = "VENDOR_HOLD"
        return _step(
            "vendor_hold",
            state="fail",
            detail=reason,
            at=hold_at,
            exception_code=exception_code,
            failure_reason=reason,
            remediation=_remediation_for(exception_code, inv),
        )

    if hold_log and (
        inv.status == InvoiceStatus.EXCEPTION
        or inv.evaluation_status == EVAL_PENDING_VENDOR
        or validate_pass is None
        or hold_log.created_at > validate_pass.created_at
    ):
        reason = _detail_from_log(hold_log, fallback=hold_event)
        exception_code = "VENDOR_HOLD"
        return _step(
            "vendor_hold",
            state="fail",
            detail=reason,
            at=hold_log.created_at,
            exception_code=exception_code,
            failure_reason=reason,
            remediation=_remediation_for(exception_code, inv),
        )

    if wm >= 11 and cleared_log is None and waived_log is None and hold_log is None:
        if inv.evaluation_status == EVAL_PENDING_VENDOR:
            return _step("vendor_hold", state="pending", detail="—")
        legacy = (
            "Customer approved — no hold (legacy run, no customer audit)"
            if is_sales
            else "Vendor approved — no hold (legacy run, no vendor audit)"
        )
        return _step(
            "vendor_hold",
            state="pass",
            detail=legacy,
            at=None,
        )
    return _step("vendor_hold", state="pending", detail="—")


def _routing_review_superseded_for_validate(
    logs: list[AuditLog],
    routing: AuditLog,
) -> bool:
    """True when a later successful gate/validation makes routing_review stale for validate."""
    gate = _routing_review_gate(routing)
    if gate == "classification":
        gate_pass = _latest_log(logs, "classification_gate_passed")
        if gate_pass and _is_after(gate_pass, routing):
            return True
        resolved = _latest_log(logs, "classification_resolved")
        if resolved and _is_after(resolved, routing):
            return True
    validate_pass = _latest_log(logs, "validation_passed")
    if validate_pass and _is_after(validate_pass, routing):
        return True
    return False


def _resolve_validate(
    inv: Invoice,
    logs: list[AuditLog],
    wm: int,
    document_types: list | None = None,
) -> DossierPipelineStepResponse:
    checks = _validation_checks(inv, document_types)
    validate_pass = _latest_log(logs, "validation_passed")
    validate_fail = _latest_log(logs, "validation_failed")
    routing_review = _latest_log(logs, "routing_review_required")
    failed_checks = [c for c in checks if c.state == "fail"]

    validation_passed_latest = validate_pass is not None and (
        validate_fail is None or validate_pass.created_at >= validate_fail.created_at
    )

    upstream_gate = _routing_review_gate(routing_review) if routing_review else ""
    if (
        routing_review
        and not validation_passed_latest
        and not _routing_review_superseded_for_validate(logs, routing_review)
        and _classification_routing_review(logs) is None
        and _playbook_routing_review(logs) is None
        and upstream_gate
        not in {
            "image_quality",
            "field_confidence",
            "vendor_classification_drift",
        }
        and (
            validate_pass is None
            or routing_review.created_at
            >= (validate_pass.created_at if validate_pass else routing_review.created_at)
        )
    ):
        reason = _detail_from_log(routing_review, fallback="routing_review_required")
        return _step(
            "validate",
            state="fail",
            detail=reason,
            at=routing_review.created_at,
            exception_code="ROUTING_REVIEW",
            failure_reason=reason,
            remediation=_REMEDIATION["ROUTING_REVIEW"],
            checks=checks,
        )

    bypass_log = _latest_log(logs, "validation_bypassed_after_human_approval")

    if failed_checks:
        reason = failed_checks[0].label
        if bypass_log is not None and validation_passed_latest:
            detail = _detail_from_log(validate_pass, fallback="validation_passed")
            detail = (
                f"{detail} — human approval waived {len(failed_checks)} failed rule(s); "
                f"first: {reason}"
            )
            return _step(
                "validate",
                state="waived",
                detail=detail,
                at=validate_pass.created_at if validate_pass else bypass_log.created_at,
                exception_code="VALIDATION_FAILED",
                failure_reason=reason,
                remediation=_REMEDIATION["VALIDATION_FAILED"],
                checks=checks,
            )
        return _step(
            "validate",
            state="fail",
            detail=reason,
            at=validate_fail.created_at if validate_fail else None,
            exception_code="VALIDATION_FAILED",
            failure_reason=reason,
            remediation=_REMEDIATION["VALIDATION_FAILED"],
            checks=checks,
        )

    if validation_passed_latest:
        detail = _detail_from_log(validate_pass, fallback="validation_passed")
        if bypass_log is not None:
            detail = f"{detail} — human approval bypassed non-vendor validation rules"
        return _step(
            "validate",
            state="pass",
            detail=detail,
            at=validate_pass.created_at,
            checks=checks,
        )

    if validate_fail and (validate_pass is None or validate_fail.created_at >= validate_pass.created_at):
        reason = _detail_from_log(validate_fail)
        return _step(
            "validate",
            state="fail",
            detail=reason,
            at=validate_fail.created_at,
            exception_code="VALIDATION_FAILED",
            failure_reason=reason,
            remediation=_REMEDIATION["VALIDATION_FAILED"],
            checks=checks,
        )

    if validate_pass or checks or wm >= 11:
        return _step(
            "validate",
            state="pass",
            detail=_detail_from_log(validate_pass, fallback="validation_passed"),
            at=validate_pass.created_at if validate_pass else None,
            checks=checks,
        )
    return _step("validate", state="pending", detail="—", checks=checks)


def _match_audit_indicates_fail(detail_dict: dict[str, object]) -> bool:
    from app.services.match.match_variance_gate_service import MATCH_FAIL_STATUSES

    match_status = str(detail_dict.get("match_status") or "").strip()
    register_status = str(detail_dict.get("status") or "").strip().lower()
    if match_status in MATCH_FAIL_STATUSES:
        return True
    if register_status == "mismatch":
        return True
    return False


def _resolve_match(
    inv: Invoice,
    logs: list[AuditLog],
    wm: int,
    document_types: list | None = None,
) -> DossierPipelineStepResponse:
    from app.services.dossier.dossier_match_service import (
        match_checks_from_summary,
        match_summary_from_audit_detail,
    )

    vr_checks = _validation_checks(inv, document_types)
    match_log = _latest_log(logs, "three_way_match_evaluated")
    variance_hold = _latest_log(logs, "three_way_match_variance_unapproved")
    purchase_variance_log = _latest_log(logs, "purchase_variance_approved")
    sales_variance_log = _latest_log(logs, "sales_variance_approved")
    variance_cleared = purchase_variance_log is not None or sales_variance_log is not None

    match_checks: list = []
    if match_log and isinstance(match_log.detail, dict):
        currency = str(match_log.detail.get("currency") or inv.currency or "SGD")
        summary = match_summary_from_audit_detail(match_log.detail, currency=currency)
        if summary is not None:
            match_checks = match_checks_from_summary(summary)

    match_fail = any(c.state == "fail" and c.rule_ref == "MATCH" for c in match_checks)
    if variance_hold is not None and not variance_cleared:
        match_fail = True

    if match_log:
        detail = _detail_from_log(match_log, fallback="three_way_match_evaluated")
        detail_dict = match_log.detail if isinstance(match_log.detail, dict) else {}
        audit_fail = _match_audit_indicates_fail(detail_dict)
        state: DossierStageState = "fail" if match_fail or audit_fail else "pass"
        failure = None
        remediation = None
        if state == "fail":
            failure = detail
            remediation = _remediation_for("MATCH_FAILED", inv)
        merged_checks = match_checks
        if vr_checks:
            seen = {row.id for row in match_checks}
            merged_checks = [
                *match_checks,
                *(row for row in vr_checks if row.id not in seen),
            ]
        return _step(
            "match",
            state=state,
            detail=detail,
            at=match_log.created_at,
            exception_code="MATCH_FAILED" if state == "fail" else None,
            failure_reason=failure,
            remediation=remediation,
            checks=merged_checks,
        )

    if variance_hold is not None and not variance_cleared:
        detail = _detail_from_log(variance_hold, fallback="three_way_match_variance_unapproved")
        return _step(
            "match",
            state="fail",
            detail=detail,
            at=variance_hold.created_at,
            exception_code="MATCH_FAILED",
            failure_reason=detail,
            remediation=_remediation_for("MATCH_FAILED", inv),
            checks=match_checks,
        )

    if purchase_variance_log or sales_variance_log:
        cleared = purchase_variance_log or sales_variance_log
        assert cleared is not None
        return _step(
            "match",
            state="pass",
            detail=_detail_from_log(cleared, fallback=cleared.event),
            at=cleared.created_at,
        )

    if match_fail:
        return _step(
            "match",
            state="fail",
            detail="Document match failed",
            at=match_log.created_at if match_log else None,
            exception_code="MATCH_FAILED",
            failure_reason="Document match failed",
            remediation=_remediation_for("MATCH_FAILED", inv),
            checks=match_checks,
        )

    from app.services.sales.so_reference import resolve_so_reference_from_invoice

    po_ref = (inv.po_reference or "").strip()
    if wm >= 13:
        if _is_sales_route(inv):
            if not resolve_so_reference_from_invoice(inv):
                return _step("match", state="waived", detail="No SO reference — match not required")
        elif not po_ref:
            return _step("match", state="waived", detail="No PO reference — match not required")
    return _step("match", state="pending", detail="—")


def _resolve_approve(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    approved_log = _latest_log(logs, "invoice_approved")
    approval_required = _latest_log(logs, "approval_required", "approval_requested", "team_expense_approval_required")

    if approved_log:
        actor = _actor_name(approved_log.detail if isinstance(approved_log.detail, dict) else None)
        detail = _detail_from_log(approved_log, fallback="Approved")
        if actor and actor not in detail:
            detail = f"Approved by {actor}"
        return _step(
            "approve",
            state="pass",
            detail=detail,
            at=approved_log.created_at,
            actor=actor,
        )

    if approval_required and inv.status == InvoiceStatus.EXCEPTION:
        detail_dict = approval_required.detail if isinstance(approval_required.detail, dict) else {}
        reason = str(detail_dict.get("reason", "")).strip() or _detail_from_log(approval_required)
        return _step(
            "approve",
            state="pending",
            detail=reason or "Waiting for approver",
            at=approval_required.created_at,
            remediation=_REMEDIATION["APPROVAL_REQUIRED"],
        )

    if wm >= 13 or inv.status == InvoiceStatus.PROCESSED:
        return _step("approve", state="pass", detail="Touchless — within policy")
    return _step("approve", state="pending", detail="—")


def _resolve_map_gl(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("map_gl", state="waived", detail="Not required — vault route")

    map_log = _latest_log(logs, "mapping_applied")
    map_review = _latest_log(logs, "mapping_review_required")
    account = (inv.account_name or "").strip()
    suspense = "suspense" in account.lower() if account else False

    if map_review and suspense and inv.status == InvoiceStatus.EXCEPTION:
        reason = _detail_from_log(map_review, fallback="mapping_review_required")
        detail_dict = map_review.detail if isinstance(map_review.detail, dict) else {}
        return _step(
            "map_gl",
            state="fail",
            detail=reason,
            at=map_review.created_at,
            exception_code="MAP_SUSPENSE",
            failure_reason=reason,
            remediation=_REMEDIATION["MAP_SUSPENSE"],
            checks=_mapping_checks(detail_dict, account),
        )

    if map_log or account:
        detail_dict = map_log.detail if map_log and isinstance(map_log.detail, dict) else {}
        detail = (
            _detail_from_log(map_log, fallback=f"mapping_applied · {account or 'GL mapped'}")
            if map_log
            else f"mapping_applied · {account or 'GL mapped'}"
        )
        evidence = []
        if inv.account_code:
            evidence.append(DossierPipelineEvidenceResponse(label="Account", ref=str(inv.account_code)))
        if inv.route_target:
            evidence.append(DossierPipelineEvidenceResponse(label="Route", ref=str(inv.route_target)))
        return _step(
            "map_gl",
            state="pass",
            detail=detail,
            at=map_log.created_at if map_log else None,
            checks=_mapping_checks(detail_dict, account) if detail_dict or account else [],
            evidence=evidence,
        )

    if wm >= 14:
        return _step("map_gl", state="pending", detail="Awaiting mapping")
    return _step("map_gl", state="pending", detail="—")


def _resolve_journal(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("journal", state="waived", detail="Not required — vault route")

    if not _map_gl_complete(inv, logs):
        return _step("journal", state="pending", detail="—")

    journal_fail = _latest_log(logs, "journal_unbalanced")
    if journal_fail and inv.status == InvoiceStatus.EXCEPTION:
        reason = _detail_from_log(journal_fail, fallback="journal_unbalanced")
        return _step(
            "journal",
            state="fail",
            detail=reason,
            at=journal_fail.created_at,
            exception_code="JOURNAL_UNBALANCED",
            failure_reason=reason,
            remediation=_REMEDIATION["JOURNAL_UNBALANCED"],
        )

    variance_fail = _latest_log(logs, "three_way_match_variance_unapproved")
    if variance_fail and inv.status == InvoiceStatus.EXCEPTION:
        reason = _detail_from_log(variance_fail, fallback="three_way_match_variance_unapproved")
        return _step(
            "journal",
            state="fail",
            detail=reason,
            at=variance_fail.created_at,
            exception_code="MATCH_FAILED",
            failure_reason=reason,
            remediation=_remediation_for("MATCH_FAILED", inv),
        )

    control_fail = _latest_log(logs, "journal_control_account_unresolved")
    if control_fail and inv.status == InvoiceStatus.EXCEPTION:
        reason = _detail_from_log(control_fail, fallback="journal_control_account_unresolved")
        return _step(
            "journal",
            state="fail",
            detail=reason,
            at=control_fail.created_at,
            exception_code="JOURNAL_CONTROL_ACCOUNT_UNRESOLVED",
            failure_reason=reason,
            remediation=_REMEDIATION["JOURNAL_CONTROL_ACCOUNT_UNRESOLVED"],
        )

    processed = _latest_log(logs, "invoice_processed", "purchase_document_processed")
    if inv.status in (InvoiceStatus.JOURNALING, InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED) or wm >= 15:
        at = processed.created_at if processed else None
        return _step(
            "journal",
            state="pass",
            detail="generate_entries — balanced journal",
            at=at,
        )
    return _step("journal", state="pending", detail="—")


def _resolve_reconcile(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("reconcile", state="waived", detail="Not required — vault route")

    if not _map_gl_complete(inv, logs):
        return _step("reconcile", state="pending", detail="—")

    recon_halt = _latest_log(logs, "reconciliation_halted")
    recon_skip = _latest_log(logs, "reconciliation_skipped")
    if recon_halt and inv.status == InvoiceStatus.EXCEPTION:
        reason = _detail_from_log(recon_halt, fallback="reconciliation_halted")
        return _step(
            "reconcile",
            state="fail",
            detail=reason,
            at=recon_halt.created_at,
            exception_code="RECON_HALTED",
            failure_reason=reason,
            remediation=_REMEDIATION["RECON_HALTED"],
        )
    if recon_skip or inv.status in (InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED) or wm >= 16:
        return _step(
            "reconcile",
            state="pass",
            detail=_detail_from_log(recon_skip, fallback="reconcile_daily cleared"),
            at=recon_skip.created_at if recon_skip else None,
        )
    return _step("reconcile", state="pending", detail="—")


def _resolve_post(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("post", state="waived", detail="Not required — vault route")

    if not _map_gl_complete(inv, logs):
        return _step("post", state="pending", detail="—")

    doc_type = (inv.purchase_document_type or "").strip().lower()
    if doc_type in ("po", "grn"):
        purchase_log = _latest_log(logs, "purchase_document_processed")
        if purchase_log or inv.status == InvoiceStatus.PROCESSED:
            return _step(
                "post",
                state="pass",
                detail=_detail_from_log(purchase_log, fallback="Supporting document processed"),
                at=purchase_log.created_at if purchase_log else None,
            )
        return _step("post", state="pending", detail="—")

    if is_published_from_audit_logs(logs):
        published_log = _latest_log(logs, "invoice_published_to_ledger")
        return _step(
            "post",
            state="pass",
            detail=_detail_from_log(published_log, fallback="invoice_published_to_ledger"),
            at=published_log.created_at if published_log else None,
            evidence=[DossierPipelineEvidenceResponse(label="Posted", ref="yes")],
        )

    processed_log = _latest_log(logs, "invoice_processed")
    if processed_log or inv.status == InvoiceStatus.PROCESSED or wm >= 17:
        return _step(
            "post",
            state="pending",
            detail="Ready to post to ledger",
            at=processed_log.created_at if processed_log else None,
        )
    return _step("post", state="pending", detail="—")


def _resolve_archive(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    vault_log = _latest_log(logs, "vault_stored")
    if vault_log:
        return _step(
            "archive",
            state="pass",
            detail=_detail_from_log(vault_log, fallback="vault_stored"),
            at=vault_log.created_at,
        )
    if (inv.route_target or "").strip().lower() == "vault" and inv.status == InvoiceStatus.PROCESSED:
        return _step("archive", state="pass", detail="vault_stored")
    return _step("archive", state="pending", detail="—")


def _resolve_pay(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("pay", state="waived", detail="Not required — vault route")
    return _step("pay", state="pending", detail="—")


_RESOLVERS = (
    _resolve_ingest,
    _resolve_duplicate,
    _resolve_storage,
    _resolve_ocr,
    _resolve_quality,
    _resolve_llm_classify,
    _resolve_confidence_gate,
    _resolve_extract,
    _resolve_document_type,
    _resolve_bundle,
    _resolve_vendor_hold,
    _resolve_validate,
    _resolve_match,
    _resolve_approve,
    _resolve_map_gl,
    _resolve_journal,
    _resolve_reconcile,
    _resolve_post,
    _resolve_pay,
    _resolve_archive,
)


def _build_raw_steps(
    inv: Invoice,
    logs: list[AuditLog],
    *,
    document_types: list | None = None,
) -> list[DossierPipelineStepResponse]:
    wm = _watermark(logs, inv)
    steps: list[DossierPipelineStepResponse] = []
    for resolver in _RESOLVERS:
        if resolver in (_resolve_validate, _resolve_match):
            steps.append(resolver(inv, logs, wm, document_types))
        else:
            steps.append(resolver(inv, logs, wm))
    return steps


def _apply_durations(steps: list[DossierPipelineStepResponse]) -> None:
    prev_at: datetime | None = None
    for i, step in enumerate(steps):
        current = _parse_at(step.at)
        if current and prev_at:
            delta_ms = max(0, int((current - prev_at).total_seconds() * 1000))
            steps[i] = step.model_copy(update={"duration_ms": delta_ms})
        if current:
            prev_at = current


def _apply_pay_stage(
    steps: list[DossierPipelineStepResponse],
    *,
    payment_status: str | None,
    payment_detail: str | None,
) -> None:
    for i, step in enumerate(steps):
        if step.stage_id != "pay":
            continue
        if payment_status == "paid":
            steps[i] = step.model_copy(
                update={"state": "pass", "detail": payment_detail or "Paid", "at": step.at}
            )
        elif payment_status == "failed":
            steps[i] = step.model_copy(
                update={
                    "state": "fail",
                    "detail": payment_detail or "Payment failed",
                    "exception_code": "PAY_FAILED",
                    "failure_reason": payment_detail or "Payment failed",
                    "remediation": _REMEDIATION["PAY_FAILED"],
                }
            )
        elif payment_status in ("awaiting", "queue", "scheduled"):
            steps[i] = step.model_copy(
                update={"state": "pending", "detail": payment_detail or "Awaiting payment approval"}
            )
        break


def _pipeline_error_stage_id(message: str) -> tuple[str, str, str]:
    """Map pipeline_error text to stage_id, exception_code, remediation key."""
    lower = message.lower()
    if "post to ledger" in lower or (
        "document type" in lower and ("configure" in lower or "not configured" in lower)
    ):
        return "map_gl", "MAP_CONFIG", "MAP_CONFIG"
    if "ocr" in lower or "parse" in lower or "stored file" in lower:
        return "extract", "PARSE_FAILED", "PARSE_FAILED"
    if "classification" in lower or "confidence" in lower:
        return "confidence_gate", "CLASSIFICATION_GATE", "CLASSIFICATION_GATE"
    if "duplicate" in lower:
        return "duplicate", "DUPLICATE_FILE", "DUPLICATE_FILE"
    return "extract", "PIPELINE_ERROR", "PIPELINE_ERROR"


def _pipeline_error_stale(logs: list[AuditLog], err_log: AuditLog) -> bool:
    for event in _PIPELINE_ERROR_SUPERSEDED_BY:
        success = _latest_log(logs, event)
        if success is not None and _is_after(success, err_log):
            return True
    return False


def _apply_pipeline_error(
    steps: list[DossierPipelineStepResponse],
    inv: Invoice,
    logs: list[AuditLog],
) -> list[DossierPipelineStepResponse]:
    """Surface audit pipeline_error on the dossier when processing aborted early."""
    if inv.status != InvoiceStatus.EXCEPTION:
        return steps
    err_log = _latest_log(logs, "pipeline_error")
    if err_log is None or _pipeline_error_stale(logs, err_log):
        return steps
    if any(step.state == "fail" for step in steps):
        return steps

    message = _detail_from_log(err_log, fallback="Pipeline processing failed")
    stage_id, exception_code, remediation_key = _pipeline_error_stage_id(message)
    try:
        stage_idx = STAGE_IDS.index(stage_id)
    except ValueError:
        return steps

    out: list[DossierPipelineStepResponse] = []
    for i, step in enumerate(steps):
        if i < stage_idx:
            out.append(step)
            continue
        if i == stage_idx:
            out.append(
                step.model_copy(
                    update={
                        "state": "fail",
                        "detail": message,
                        "at": _fmt_at(err_log.created_at),
                        "exception_code": exception_code,
                        "failure_reason": message,
                        "remediation": _REMEDIATION.get(remediation_key, _REMEDIATION["PIPELINE_ERROR"]),
                        "blocked_reason": None,
                    }
                )
            )
            continue
        if step.state in ("fail", "waived"):
            out.append(step)
            continue
        blocked_detail = step.detail if step.detail and step.detail != "—" else None
        out.append(
            step.model_copy(
                update={
                    "state": "pending",
                    "detail": blocked_detail or "—",
                    "blocked_reason": None,
                    "exception_code": None,
                    "failure_reason": None,
                    "remediation": None,
                }
            )
        )
    return out


def _apply_blocked_downstream(steps: list[DossierPipelineStepResponse]) -> list[DossierPipelineStepResponse]:
    fail_idx: int | None = None
    for i, step in enumerate(steps):
        if step.state == "fail":
            fail_idx = i
            break

    bottleneck_idx: int | None = None
    if fail_idx is None:
        for i, step in enumerate(steps):
            if step.state != "pending" or not step.detail or step.detail == "—":
                continue
            if any(steps[j].state == "pass" for j in range(i + 1, len(steps))):
                bottleneck_idx = i
                break

    block_idx = fail_idx if fail_idx is not None else bottleneck_idx
    if block_idx is None:
        return steps

    block_label = _STAGE_LABELS.get(steps[block_idx].stage_id, steps[block_idx].stage_id)
    block_prefix = "must pass" if fail_idx is not None else "must complete"
    out: list[DossierPipelineStepResponse] = []
    for i, step in enumerate(steps):
        if i <= block_idx:
            out.append(step)
            continue
        if step.state in ("fail", "waived"):
            out.append(step)
            continue
        if fail_idx is None and step.state in ("pass", "waived"):
            out.append(step)
            continue
        if step.state == "pending" and step.blocked_reason:
            out.append(step)
            continue
        blocked_detail = step.detail if step.detail and step.detail != "—" else None
        out.append(
            step.model_copy(
                update={
                    "state": "pending",
                    "detail": blocked_detail or "—",
                    "blocked_reason": (
                        f'Blocked — upstream stage "{block_label}" {block_prefix} before this stage can run.'
                    ),
                    "exception_code": None,
                    "failure_reason": None,
                    "remediation": None,
                }
            )
        )
    return out


def build_dossier_pipeline(
    inv: Invoice,
    logs: list[AuditLog],
    *,
    payment_status: str | None = None,
    payment_detail: str | None = None,
    compact: bool = False,
    document_types: list | None = None,
) -> list[DossierPipelineStepResponse]:
    cycle_logs = _cycle_logs(logs)
    steps = _build_raw_steps(inv, cycle_logs, document_types=document_types)
    steps = _apply_pipeline_error(steps, inv, cycle_logs)
    _apply_pay_stage(steps, payment_status=payment_status, payment_detail=payment_detail)
    steps = _apply_blocked_downstream(steps)
    _apply_durations(steps)

    if len(steps) != len(STAGE_IDS):
        raise RuntimeError(f"expected {len(STAGE_IDS)} pipeline stages, got {len(steps)}")

    if compact:
        compacted: list[DossierPipelineStepResponse] = []
        for step in steps:
            if step.state == "fail":
                compacted.append(
                    step.model_copy(update={"checks": [], "evidence": []})
                )
            else:
                compacted.append(
                    step.model_copy(
                        update={
                            "checks": [],
                            "evidence": [],
                            "failure_reason": None,
                            "remediation": None,
                        }
                    )
                )
        return compacted
    return steps


def first_pipeline_failure(steps: list[DossierPipelineStepResponse]) -> DossierPipelineStepResponse | None:
    for step in steps:
        if step.state == "fail":
            return step
    return None
