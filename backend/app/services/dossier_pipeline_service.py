"""Build 15-stage dossier pipeline from invoice state + audit trail.

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
from app.services.audit_change_summary import summarize_audit_change
from app.services.pipeline_stages import (
    _actor_name,
    _latest_log,
    _source_label,
    _validation_results,
)
from app.services.publish_service import is_published_from_audit_logs

DossierStageState = Literal["pass", "fail", "waived", "pending"]

_VAULT_ROUTE = "vault"


def _is_vault_route(inv: Invoice) -> bool:
    return (inv.route_target or "").strip().lower() == _VAULT_ROUTE


STAGE_IDS: tuple[str, ...] = (
    "ingest",
    "duplicate",
    "extract",
    "classify",
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
    "extract": "Extract",
    "classify": "Classify",
    "bundle": "Bundle / Playbook",
    "vendor_hold": "Vendor hold",
    "validate": "Validate",
    "match": "Match",
    "approve": "Approve",
    "map_gl": "Map GL",
    "journal": "Journal",
    "reconcile": "Reconcile",
    "post": "Process",
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
        "parse_completed": 2,
        "invoice_parsed": 2,
        "parsing_failed": 2,
        "document_classified": 3,
        "playbook_evaluated": 4,
        "vendor_registration_hold": 5,
        "validation_passed": 6,
        "validation_failed": 6,
        "routing_review_required": 6,
        "three_way_match_evaluated": 7,
        "purchase_variance_approved": 7,
        "invoice_approved": 8,
        "approval_required": 8,
        "approval_requested": 8,
        "team_expense_approval_required": 8,
        "mapping_applied": 9,
        "mapping_review_required": 9,
        "reconciliation_halted": 11,
        "reconciliation_skipped": 11,
        "invoice_processed": 12,
        "invoice_published_to_ledger": 12,
        "purchase_document_processed": 12,
        "vault_stored": 14,
    }
)

_STATUS_FLOOR: dict[InvoiceStatus, int] = {
    InvoiceStatus.PENDING: 0,
    InvoiceStatus.PARSING: 2,
    InvoiceStatus.VALIDATING: 6,
    InvoiceStatus.MAPPING: 9,
    InvoiceStatus.JOURNALING: 10,
    InvoiceStatus.RECONCILING: 11,
    InvoiceStatus.PROCESSED: 12,
    InvoiceStatus.DUPLICATE_SKIPPED: 1,
    InvoiceStatus.REJECTED: 0,
}

_REMEDIATION: dict[str, str] = {
    "DUPLICATE_FILE": "Use the existing dossier or request a controlled re-ingest if the prior file was wrong.",
    "PARSE_FAILED": "Re-upload a readable PDF or fix the stored file path, then reprocess.",
    "BUNDLE_INCOMPLETE": "Upload the missing mandatory bundle documents on the same linkage key.",
    "VENDOR_HOLD": "Approve the vendor in Vendor Masters or clear the registration hold.",
    "VALIDATION_FAILED": "Correct the document or override failed validation rules in the exception queue.",
    "ROUTING_REVIEW": "Confirm document type classification or adjust rule-book routing.",
    "DOCUMENT_UNCLASSIFIED": "Classify the document type in Rule Book or reclassify from the exception queue.",
    "MATCH_FAILED": "Link PO/GRN, approve variance, or update purchase register lines.",
    "APPROVAL_REQUIRED": "Route to the approver named in the playbook policy.",
    "MAP_SUSPENSE": "Map to a real GL account in the rule book or approve suspense mapping.",
    "RECON_HALTED": "Clear the daily reconciliation halt before posting.",
    "PAY_FAILED": "Review payment details and re-release from the payments queue.",
}


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


def _watermark(logs: list[AuditLog], inv: Invoice) -> int:
    wm = _STATUS_FLOOR.get(inv.status, -1)
    for entry in logs:
        idx = _EVENT_STAGE.get(entry.event)
        if idx is not None:
            wm = max(wm, idx)
    if inv.status == InvoiceStatus.EXCEPTION:
        # Exception can stop anywhere — trust audit trail, not status floor.
        wm = max(( _EVENT_STAGE.get(e.event, -1) for e in logs), default=-1)
    return wm


def _validation_checks(inv: Invoice) -> list[DossierPipelineCheckResponse]:
    checks: list[DossierPipelineCheckResponse] = []
    for row in _validation_results(inv):
        rule = str(row.get("rule", "")).strip() or "rule"
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


def _bundle_checks(detail: dict[str, object]) -> list[DossierPipelineCheckResponse]:
    checks: list[DossierPipelineCheckResponse] = []
    missing = detail.get("missing_bundle_mandatory") or []
    if isinstance(missing, list):
        for code in missing:
            token = str(code).strip()
            if token:
                checks.append(
                    DossierPipelineCheckResponse(
                        id=f"bundle-{token.lower()}",
                        label=f"Mandatory bundle member {token}",
                        state="fail",
                        rule_ref="VR-PB01",
                        detail=f"{token} not on file",
                    )
                )
    if not checks and not detail.get("blocks_posting"):
        checks.append(
            DossierPipelineCheckResponse(
                id="bundle-ok",
                label="Playbook bundle satisfied",
                state="pass",
                rule_ref="VR-PB01",
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


def _classification_routing_review(logs: list[AuditLog]) -> AuditLog | None:
    routing = _latest_log(logs, "routing_review_required")
    if routing is None:
        return None
    validate_pass = _latest_log(logs, "validation_passed")
    if validate_pass and validate_pass.created_at > routing.created_at:
        return None
    gate = _routing_review_gate(routing)
    detail = _routing_review_detail(routing)
    if gate == "classification":
        return routing
    if gate == "playbook":
        return None
    if detail.get("no_classifier_match"):
        return routing
    if gate == "" and validate_pass is None:
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


def _resolve_duplicate(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    dup_log = _latest_log(
        logs, "duplicate_skipped", "duplicate_in_progress", "duplicate_reingest_rejected"
    )
    if inv.status == InvoiceStatus.DUPLICATE_SKIPPED or (
        dup_log and dup_log.event == "duplicate_skipped"
    ):
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
        return _step(
            "duplicate",
            state="pending",
            detail=_detail_from_log(dup_log),
            at=dup_log.created_at,
        )
    if wm >= 2:
        ingest_log = _latest_log(logs, "email_ingested", "invoice_uploaded", "invoice_file_attached")
        return _step(
            "duplicate",
            state="pass",
            detail="File hash unique",
            at=ingest_log.created_at if ingest_log else inv.created_at,
        )
    return _step("duplicate", state="pending", detail="—")


def _resolve_extract(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    parse_completed = _latest_log(logs, "parse_completed", "invoice_parsed")
    parse_failed = _latest_log(logs, "parsing_failed")
    parse_log = parse_completed
    if parse_failed and parse_completed:
        if parse_completed.created_at >= parse_failed.created_at:
            parse_log = parse_completed
        elif (inv.vendor or inv.invoice_no or (inv.document_type_code or "").strip()):
            # Stale parsing_failed from a concurrent re-run after a successful extract.
            parse_log = parse_completed
        else:
            parse_log = parse_failed
    elif parse_failed and not parse_completed:
        parse_log = parse_failed

    if parse_log and parse_log.event == "parsing_failed":
        reason = _detail_from_log(parse_log, fallback="Could not read document")
        return _step(
            "extract",
            state="fail",
            detail=reason,
            at=parse_log.created_at,
            exception_code="PARSE_FAILED",
            failure_reason=reason,
            remediation=_REMEDIATION["PARSE_FAILED"],
        )
    if parse_log:
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
    if wm >= 3 and (inv.vendor or inv.invoice_no):
        return _step(
            "extract",
            state="pass",
            detail="Fields extracted",
            at=inv.created_at,
        )
    return _step("extract", state="pending", detail="—")


def _resolve_classify(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    classification_review = _classification_routing_review(logs)
    if classification_review:
        detail = _detail_from_log(classification_review, fallback="Document type not classified")
        detail_dict = _routing_review_detail(classification_review)
        reason = str(detail_dict.get("reason") or detail).strip() or "Document type not classified"
        return _step(
            "classify",
            state="fail",
            detail=reason,
            at=classification_review.created_at,
            exception_code="DOCUMENT_UNCLASSIFIED",
            failure_reason=reason,
            remediation=_REMEDIATION["DOCUMENT_UNCLASSIFIED"],
        )

    classify_log = _latest_log(logs, "document_classified")
    code = (inv.document_type_code or "").strip()
    if classify_log:
        detail = _detail_from_log(classify_log, fallback=f"document_classified · {code}" if code else "document_classified")
        return _step("classify", state="pass", detail=detail, at=classify_log.created_at)
    if code and wm >= 3:
        conf = _confidence_label(inv.document_type_confidence)
        detail = f"document_classified · {code}"
        if conf:
            detail = f"{detail} · conf {conf}"
        return _step("classify", state="pass", detail=detail)
    return _step("classify", state="pending", detail="—")


def _resolve_bundle(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    playbook_review = _playbook_routing_review(logs)
    if playbook_review:
        detail_dict = _routing_review_detail(playbook_review)
        missing = detail_dict.get("missing_bundle_mandatory") or []
        if not missing and isinstance(detail_dict.get("playbook"), dict):
            missing = detail_dict["playbook"].get("missing_bundle_mandatory") or []
        reason = _detail_from_log(playbook_review, fallback="Playbook blocks posting")
        failure = (
            f"Mandatory bundle missing: {', '.join(str(m) for m in missing)}"
            if missing
            else reason
        )
        return _step(
            "bundle",
            state="fail",
            detail=reason,
            at=playbook_review.created_at,
            exception_code="BUNDLE_INCOMPLETE",
            failure_reason=failure,
            remediation=_REMEDIATION["BUNDLE_INCOMPLETE"],
            checks=_bundle_checks(detail_dict if detail_dict else {"blocks_posting": True}),
        )

    bundle_log = _latest_log(logs, "playbook_evaluated")
    if bundle_log:
        detail_dict = bundle_log.detail if isinstance(bundle_log.detail, dict) else {}
        missing = detail_dict.get("missing_bundle_mandatory") or []
        blocks = bool(detail_dict.get("blocks_posting")) or bool(missing)
        state: DossierStageState = "fail" if blocks else "pass"
        detail = _detail_from_log(bundle_log, fallback="playbook_evaluated")
        checks = _bundle_checks(detail_dict)
        failure = None
        remediation = None
        if state == "fail":
            failure = (
                f"Mandatory bundle missing: {', '.join(str(m) for m in missing)}"
                if missing
                else "Playbook blocks posting"
            )
            remediation = _REMEDIATION["BUNDLE_INCOMPLETE"]
        return _step(
            "bundle",
            state=state,
            detail=detail,
            at=bundle_log.created_at,
            exception_code="BUNDLE_INCOMPLETE" if state == "fail" else None,
            failure_reason=failure,
            remediation=remediation,
            checks=checks,
        )
    if wm >= 4:
        return _step("bundle", state="pass", detail="playbook_evaluated")
    return _step("bundle", state="pending", detail="—")


def _resolve_vendor_hold(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    hold_log = _latest_log(logs, "vendor_registration_hold")
    validate_pass = _latest_log(logs, "validation_passed")
    if hold_log and (
        inv.status == InvoiceStatus.EXCEPTION
        or validate_pass is None
        or hold_log.created_at > validate_pass.created_at
    ):
        reason = _detail_from_log(hold_log, fallback="vendor_registration_hold")
        return _step(
            "vendor_hold",
            state="fail",
            detail=reason,
            at=hold_log.created_at,
            exception_code="VENDOR_HOLD",
            failure_reason=reason,
            remediation=_REMEDIATION["VENDOR_HOLD"],
        )
    if wm >= 6:
        return _step(
            "vendor_hold",
            state="pass",
            detail="Vendor approved — no hold",
            at=hold_log.created_at if hold_log else None,
        )
    return _step("vendor_hold", state="pending", detail="—")


def _resolve_validate(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    checks = _validation_checks(inv)
    validate_pass = _latest_log(logs, "validation_passed")
    validate_fail = _latest_log(logs, "validation_failed")
    routing_review = _latest_log(logs, "routing_review_required")
    failed_checks = [c for c in checks if c.state == "fail"]

    if routing_review and _classification_routing_review(logs) is None and _playbook_routing_review(logs) is None and (
        inv.status == InvoiceStatus.EXCEPTION
        or validate_pass is None
        or routing_review.created_at >= (validate_pass.created_at if validate_pass else routing_review.created_at)
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

    validation_passed_latest = validate_pass is not None and (
        validate_fail is None or validate_pass.created_at >= validate_fail.created_at
    )
    if validation_passed_latest:
        return _step(
            "validate",
            state="pass",
            detail=_detail_from_log(validate_pass, fallback="validation_passed"),
            at=validate_pass.created_at,
            checks=checks,
        )

    if failed_checks or (
        validate_fail and (validate_pass is None or validate_fail.created_at >= validate_pass.created_at)
    ):
        reason = failed_checks[0].label if failed_checks else _detail_from_log(validate_fail)
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

    if validate_pass or checks or wm >= 6:
        return _step(
            "validate",
            state="pass",
            detail=_detail_from_log(validate_pass, fallback="validation_passed"),
            at=validate_pass.created_at if validate_pass else None,
            checks=checks,
        )
    return _step("validate", state="pending", detail="—", checks=checks)


def _resolve_match(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    checks = _validation_checks(inv)
    vr15_fail = any(c.state == "fail" and c.rule_ref == "VR15" for c in checks)
    match_log = _latest_log(logs, "three_way_match_evaluated")
    variance_log = _latest_log(logs, "purchase_variance_approved")

    if match_log:
        detail = _detail_from_log(match_log, fallback="three_way_match_evaluated")
        detail_dict = match_log.detail if isinstance(match_log.detail, dict) else {}
        status = str(detail_dict.get("status") or detail_dict.get("match_status") or "").lower()
        state: DossierStageState = "fail" if vr15_fail or any(
            token in status for token in ("variance", "no grn", "routed")
        ) else "pass"
        failure = None
        remediation = None
        if state == "fail":
            failure = detail
            remediation = _REMEDIATION["MATCH_FAILED"]
        return _step(
            "match",
            state=state,
            detail=detail,
            at=match_log.created_at,
            exception_code="MATCH_FAILED" if state == "fail" else None,
            failure_reason=failure,
            remediation=remediation,
        )

    if variance_log:
        return _step(
            "match",
            state="pass",
            detail=_detail_from_log(variance_log, fallback="purchase_variance_approved"),
            at=variance_log.created_at,
        )

    if vr15_fail:
        return _step(
            "match",
            state="fail",
            detail="VR15 three-way match failed",
            exception_code="MATCH_FAILED",
            failure_reason="VR15 three-way match failed",
            remediation=_REMEDIATION["MATCH_FAILED"],
        )

    po_ref = (inv.po_reference or "").strip()
    if wm >= 9 and not po_ref:
        return _step("match", state="waived", detail="No PO reference — match not required")
    if wm >= 7 and inv.status == InvoiceStatus.PROCESSED:
        return _step("match", state="waived", detail="Match not required for this route")
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

    if wm >= 9 or inv.status == InvoiceStatus.PROCESSED:
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

    if wm >= 9:
        return _step("map_gl", state="pending", detail="Awaiting mapping")
    return _step("map_gl", state="pending", detail="—")


def _resolve_journal(inv: Invoice, logs: list[AuditLog], wm: int) -> DossierPipelineStepResponse:
    if _is_vault_route(inv):
        return _step("journal", state="waived", detail="Not required — vault route")

    processed = _latest_log(logs, "invoice_processed", "purchase_document_processed")
    if inv.status in (InvoiceStatus.JOURNALING, InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED) or wm >= 10:
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
    if recon_skip or inv.status in (InvoiceStatus.RECONCILING, InvoiceStatus.PROCESSED) or wm >= 11:
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
            evidence=[DossierPipelineEvidenceResponse(label="Published", ref="yes")],
        )

    processed_log = _latest_log(logs, "invoice_processed")
    if processed_log or inv.status == InvoiceStatus.PROCESSED or wm >= 12:
        return _step(
            "post",
            state="pending",
            detail="Ready to publish to ledger",
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
    _resolve_extract,
    _resolve_classify,
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


def _build_raw_steps(inv: Invoice, logs: list[AuditLog]) -> list[DossierPipelineStepResponse]:
    wm = _watermark(logs, inv)
    return [resolver(inv, logs, wm) for resolver in _RESOLVERS]


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


def _apply_blocked_downstream(steps: list[DossierPipelineStepResponse]) -> list[DossierPipelineStepResponse]:
    fail_idx: int | None = None
    for i, step in enumerate(steps):
        if step.state == "fail":
            fail_idx = i
            break
    if fail_idx is None:
        return steps
    fail_label = _STAGE_LABELS.get(steps[fail_idx].stage_id, steps[fail_idx].stage_id)
    out: list[DossierPipelineStepResponse] = []
    for i, step in enumerate(steps):
        if i <= fail_idx:
            out.append(step)
            continue
        if step.state == "fail":
            out.append(step)
            continue
        out.append(
            step.model_copy(
                update={
                    "state": "pending",
                    "blocked_reason": (
                        f'Blocked — upstream stage "{fail_label}" must pass before this stage can run.'
                    ),
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
) -> list[DossierPipelineStepResponse]:
    steps = _build_raw_steps(inv, logs)
    _apply_pay_stage(steps, payment_status=payment_status, payment_detail=payment_detail)
    steps = _apply_blocked_downstream(steps)
    _apply_durations(steps)

    if len(steps) != len(STAGE_IDS):
        raise RuntimeError(f"expected {len(STAGE_IDS)} pipeline stages, got {len(steps)}")

    if compact:
        return [
            step.model_copy(
                update={"checks": [], "evidence": [], "failure_reason": None, "remediation": None}
            )
            for step in steps
        ]
    return steps


def first_pipeline_failure(steps: list[DossierPipelineStepResponse]) -> DossierPipelineStepResponse | None:
    for step in steps:
        if step.state == "fail":
            return step
    return None
