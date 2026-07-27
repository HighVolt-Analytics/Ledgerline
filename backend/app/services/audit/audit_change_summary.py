"""Human-readable audit change summaries for CSV export."""

from __future__ import annotations

import json
from typing import Any

from app.services.audit.audit_detail_helpers import truncate_audit_error

_RULE_LIST_SECTIONS = frozenset(
    {
        "email_capture_rules",
        "purchase_rules",
        "expense_rules",
        "team_expense_rules",
        "document_sets",
    }
)

_PURCHASE_SYNC_EVENTS = frozenset(
    {
        "purchase_po_document_synced",
        "purchase_grn_document_synced",
        "purchase_invoice_document_synced",
    }
)


def _format_money(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"${int(number)}"
    return f"${number:.2f}"


def _rule_count_label(count: int, noun: str) -> str:
    return f"{count} {noun} added" if count == 1 else f"{count} {noun}s added"


def _summarize_rule_book_updated(detail: dict[str, Any]) -> str:
    changes = detail.get("changes")
    if not isinstance(changes, dict):
        return "Rule book updated"

    parts: list[str] = []
    for section, diff in changes.items():
        if section not in _RULE_LIST_SECTIONS or not isinstance(diff, dict):
            continue
        added = diff.get("added") or []
        removed = diff.get("removed") or []
        modified = diff.get("modified") or []
        if added:
            parts.append(f"{_rule_count_label(len(added), 'rule')} to {section}")
        if removed:
            label = "rule" if len(removed) == 1 else "rules"
            parts.append(f"{len(removed)} {label} removed from {section}")
        for rule_id in modified:
            parts.append(f"Rule {rule_id} modified")

    return "; ".join(parts) if parts else "Rule book updated"


def _summarize_unmatched_expense_vendor(detail: dict[str, Any]) -> str:
    confidence = detail.get("vendor_confidence")
    threshold = detail.get("threshold")
    amount = detail.get("amount")
    hold_above = detail.get("hold_above")

    parts: list[str] = []
    if confidence is not None:
        parts.append(f"Vendor confidence: {confidence}")
    if threshold is not None:
        parts.append(f"below threshold {threshold}")
    if amount is not None and hold_above is not None:
        parts.append(
            f"amount {_format_money(amount)} under hold limit {_format_money(hold_above)}"
        )
    elif amount is not None:
        parts.append(f"amount {_format_money(amount)}")
    return ", ".join(parts) if parts else "Unmatched expense vendor"


def _summarize_purchase_sync(event: str, detail: dict[str, Any]) -> str:
    po_number = str(detail.get("po_number") or "").strip()
    match_status = str(detail.get("match_status") or "").strip()
    three_way = str(detail.get("three_way_status") or detail.get("status") or "").strip()
    match_suffix = ""
    if match_status and three_way:
        match_suffix = f" ({match_status}, {three_way})"
    elif match_status:
        match_suffix = f" ({match_status})"
    elif three_way:
        match_suffix = f" ({three_way})"

    if not po_number:
        return f"Purchase document synced{match_suffix}" if match_suffix else "Purchase document synced"
    if event == "purchase_po_document_synced":
        return f"{po_number} PO document linked{match_suffix}"
    if event == "purchase_grn_document_synced":
        return f"{po_number} GRN document linked{match_suffix}"
    return f"{po_number} invoice linked{match_suffix}"


def _rule_match_label(rule_type: str, match_reason: str) -> str:
    prefix = f"{rule_type}:"
    if match_reason.lower().startswith(prefix.lower()):
        return match_reason
    return f"{rule_type}: {match_reason}"


def _summarize_mapping_applied(detail: dict[str, Any]) -> str:
    account = str(detail.get("account_name") or detail.get("account_code") or "").strip()
    rule_type = str(detail.get("rule_type") or "").strip()
    match_reason = str(detail.get("match_reason") or "").strip()
    if account and rule_type and match_reason:
        return f"Mapped to {account} ({_rule_match_label(rule_type, match_reason)})"
    if account:
        return f"Mapped to {account}"
    if rule_type and match_reason:
        return _rule_match_label(rule_type, match_reason)
    return "Account mapping applied"


def _summarize_vendor_hold(detail: dict[str, Any]) -> str:
    vendor = str(detail.get("vendor") or detail.get("vendor_name") or "").strip()
    confidence = detail.get("vendor_confidence")
    if vendor and confidence is not None:
        return f"{vendor}: vendor confidence {confidence}, registration hold"
    if vendor:
        return f"{vendor}: vendor registration hold"
    return "Vendor registration hold"


def _summarize_customer_hold(detail: dict[str, Any]) -> str:
    customer = str(detail.get("customer") or detail.get("vendor") or "").strip()
    confidence = detail.get("customer_confidence", detail.get("vendor_confidence"))
    if customer and confidence is not None:
        return f"{customer}: customer confidence {confidence}, registration hold"
    if customer:
        return f"{customer}: customer registration hold"
    return "Customer registration hold"


def _summarize_vendor_cleared(detail: dict[str, Any]) -> str:
    vendor = str(detail.get("vendor") or "").strip()
    reason = str(detail.get("reason") or "").strip()
    labels = {
        "vendor_in_master": "registered vendor master match",
        "confidence_above_threshold": "vendor confidence above threshold",
        "po_vendor_aligned": "aligned with PO register vendor",
    }
    label = labels.get(reason, reason.replace("_", " ") if reason else "vendor check passed")
    if vendor:
        return f"{vendor}: {label}"
    return label.capitalize() if label else "Vendor registration check passed"


def _summarize_customer_cleared(detail: dict[str, Any]) -> str:
    customer = str(detail.get("customer") or detail.get("vendor") or "").strip()
    reason = str(detail.get("reason") or "").strip()
    labels = {
        "customer_in_master": "registered customer master match",
        "confidence_above_threshold": "customer confidence above threshold",
    }
    label = labels.get(reason, reason.replace("_", " ") if reason else "customer check passed")
    if customer:
        return f"{customer}: {label}"
    return label.capitalize() if label else "Customer registration check passed"


def _summarize_customer_waived(detail: dict[str, Any]) -> str:
    reason = str(detail.get("reason") or "").strip()
    labels = {
        "registration_not_required": "VR12 not required for this sales document",
    }
    return labels.get(reason, reason.replace("_", " ") if reason else "Customer hold not required")


def _summarize_vendor_waived(detail: dict[str, Any]) -> str:
    reason = str(detail.get("reason") or "").strip()
    labels = {
        "registration_not_required": "VR12 not required for this document route",
        "supporting_purchase_document": "supporting PO/GRN document",
        "po_register_trusted": "PO register vendor trusted",
    }
    return labels.get(reason, reason.replace("_", " ") if reason else "Vendor hold not required")


def _summarize_parse_completed(detail: dict[str, Any]) -> str:
    source = str(detail.get("source") or "").strip()
    confidence = str(detail.get("confidence") or "").strip()
    text_length = detail.get("text_length")
    parts: list[str] = []
    if source:
        parts.append(f"Parsed via {source}")
    if confidence:
        parts.append(f"{confidence} confidence")
    if text_length is not None:
        parts.append(f"{text_length} chars extracted")
    return ", ".join(parts) if parts else "Parse completed"


def _duplicate_match_label(detail: dict[str, Any]) -> str | None:
    """Prefer stable DOC-ref / invoice number over internal DB id."""
    original_ref = str(detail.get("original_document_ref") or "").strip()
    if original_ref:
        return f"matches {original_ref}"
    original_no = str(
        detail.get("original_invoice_no") or detail.get("invoice_no") or ""
    ).strip()
    if original_no:
        return f"matches {original_no}"
    # Legacy audits only stored the DB id — avoid surfacing raw ids in the UI.
    if isinstance(detail.get("original_invoice_id"), int):
        return "matches original document"
    return None


def _summarize_duplicate_skipped(detail: dict[str, Any]) -> str:
    filename = str(detail.get("filename") or detail.get("attachment") or "").strip()
    source = str(detail.get("source") or "").strip()
    parts = ["Duplicate file skipped"]
    match_label = _duplicate_match_label(detail)
    if match_label:
        parts.append(match_label)
    if filename:
        parts.append(f"file: {filename}")
    if source:
        parts.append(f"via {source}")
    return " · ".join(parts)


def _summarize_duplicate_in_progress(detail: dict[str, Any]) -> str:
    filename = str(detail.get("filename") or detail.get("attachment") or "").strip()
    source = str(detail.get("source") or "").strip()
    parts = ["Duplicate blocked — original still processing"]
    if filename:
        parts.append(f"file: {filename}")
    if source:
        parts.append(f"via {source}")
    return " · ".join(parts)


def _summarize_duplicate_reingest_rejected(detail: dict[str, Any]) -> str:
    filename = str(detail.get("filename") or "").strip()
    source = str(detail.get("source") or "").strip()
    parts = ["Rejected document resubmitted"]
    if filename:
        parts.append(f"file: {filename}")
    if source:
        parts.append(f"via {source}")
    return " · ".join(parts)


def _summarize_ingest_capture(detail: dict[str, Any]) -> str:
    rule_name = str(detail.get("rule_name") or "").strip()
    attachment = str(detail.get("attachment") or "").strip()
    parts: list[str] = ["Ingestion rule matched"]
    if rule_name:
        parts.append(f"rule: {rule_name}")
    if attachment:
        parts.append(f"file: {attachment}")
    return " · ".join(parts)


def _format_vr_rows(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    checks: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        check_id = str(row.get("check_id") or "").strip()
        result = str(row.get("result") or "").strip()
        name = str(row.get("name") or check_id).strip()
        if name and result:
            checks.append(f"{name}: {result}")
    return "; ".join(checks)


def _summarize_validation_results(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    vr_te = _format_vr_rows(detail.get("vr_te_results"))
    if vr_te:
        parts.append(vr_te)
    vr_core = _format_vr_rows(detail.get("vr_results"))
    if vr_core:
        parts.append(vr_core)
    return " · ".join(parts)


def summarize_audit_change(
    event: str,
    detail: dict[str, Any] | None,
    *,
    validation_results_json: str | None = None,
) -> str:
    """Build a one-line auditor-facing summary from event + detail JSON."""
    d = detail if isinstance(detail, dict) else {}

    if event == "rule_book_updated":
        return _summarize_rule_book_updated(d)
    if event == "parse_completed":
        return _summarize_parse_completed(d)
    if event == "duplicate_skipped":
        return _summarize_duplicate_skipped(d)
    if event == "duplicate_in_progress":
        return _summarize_duplicate_in_progress(d)
    if event == "duplicate_reingest_rejected":
        return _summarize_duplicate_reingest_rejected(d)
    if event == "ingest_capture_matched":
        return _summarize_ingest_capture(d)
    if event in ("validation_passed", "validation_failed"):
        vr_summary = _summarize_validation_results(d)
        if vr_summary:
            prefix = "Validation passed" if event == "validation_passed" else "Validation failed"
            return f"{prefix} — {vr_summary}"
        if validation_results_json:
            try:
                rows = json.loads(validation_results_json)
            except (json.JSONDecodeError, TypeError):
                rows = []
            if isinstance(rows, list) and rows:
                failed = [
                    str(r.get("rule", ""))
                    for r in rows
                    if isinstance(r, dict) and not r.get("passed")
                ]
                if failed and event == "validation_failed":
                    return f"Failed checks: {', '.join(failed)}"
                passed = [
                    str(r.get("rule", ""))
                    for r in rows
                    if isinstance(r, dict) and r.get("passed")
                ]
                if passed and event == "validation_passed":
                    return f"Passed: {', '.join(passed)}"
        return "Validation passed" if event == "validation_passed" else "Validation failed"
    if event == "unmatched_expense_vendor":
        return _summarize_unmatched_expense_vendor(d)
    if event in _PURCHASE_SYNC_EVENTS:
        return _summarize_purchase_sync(event, d)
    if event == "mapping_applied":
        return _summarize_mapping_applied(d)
    if event == "vendor_registration_hold":
        return _summarize_vendor_hold(d)
    if event == "customer_registration_hold":
        return _summarize_customer_hold(d)
    if event == "customer_registration_cleared":
        return _summarize_customer_cleared(d)
    if event == "customer_registration_waived":
        return _summarize_customer_waived(d)
    if event == "vendor_registration_cleared":
        return _summarize_vendor_cleared(d)
    if event == "vendor_registration_waived":
        return _summarize_vendor_waived(d)
    if event == "unmatched_team_vendor":
        vendor = str(d.get("vendor_name") or d.get("vendor") or "").strip()
        score = d.get("confidence_score", d.get("vendor_confidence"))
        if vendor and score is not None:
            return f"{vendor}: team vendor confidence {score}, below threshold"
        if vendor:
            return f"{vendor}: unmatched team vendor"
        return "Unmatched team vendor"
    if event == "reconciliation_skipped":
        reason = str(d.get("reason") or "").strip()
        return reason or "Reconciliation skipped"
    if event == "email_moved":
        folder = str(d.get("folder") or "").strip()
        reason = str(d.get("reason") or "").strip()
        outcome = str(d.get("outcome") or "").strip()
        if folder and reason:
            return f"Moved to {folder}: {reason}"
        if folder:
            return f"Moved to {folder}"
        if reason:
            return reason
        if outcome:
            return f"Email moved ({outcome})"
        return "Email moved"
    if event == "team_expense_approval_required":
        amount = d.get("amount")
        rule_id = str(d.get("rule_id") or "").strip()
        if amount is not None and rule_id:
            return f"Manual approval required — {_format_money(amount)}, rule {rule_id}"
        if amount is not None:
            return f"Manual approval required — {_format_money(amount)}"
        return "Team expense approval required"
    if event == "three_way_match_evaluated":
        status = str(d.get("status") or d.get("match_status") or "").strip()
        po_number = str(d.get("po_number") or "").strip()
        if po_number and status:
            return f"{po_number}: {status}"
        return status or "Three-way match evaluated"
    if event == "invoice_approved":
        prev = str(d.get("previous_status") or "").strip()
        return f"Approved for reprocess (was {prev})" if prev else "Approved for reprocess"
    if event == "invoice_rejected":
        prev = str(d.get("previous_status") or "").strip()
        return f"Rejected (was {prev})" if prev else "Invoice rejected"
    if event == "invoice_processed":
        route = str(d.get("route_target") or "").strip()
        vendor = str(d.get("vendor") or "").strip()
        amount = d.get("amount")
        parts: list[str] = ["Processed"]
        if route:
            parts.append(route)
        if vendor:
            parts.append(vendor)
        if amount is not None:
            parts.append(_format_money(amount))
        return " — ".join(parts) if len(parts) > 1 else "Invoice processed"
    if event == "email_ingested":
        sender = str(d.get("sender") or "").strip()
        subject = str(d.get("subject") or "").strip()
        if sender and subject:
            return f"Email from {sender}: {subject}"
        if sender:
            return f"Email from {sender}"
        return "Email ingested"
    if event == "blob_relocated":
        to_path = str(d.get("to_path") or d.get("path") or "").strip()
        if to_path:
            return f"File stored at {to_path}"
        return "Blob relocated"
    if event == "pipeline_error":
        ref = str(d.get("document_ref") or "").strip()
        err = truncate_audit_error(str(d.get("error") or d.get("reason") or ""))
        if ref and err:
            return f"Pipeline error ({ref}): {err}"
        if ref:
            return f"Pipeline error ({ref})"
        return f"Pipeline error: {err}" if err else "Pipeline error"
    if event == "payment_status_updated":
        prev = str(d.get("previous_status") or "").strip()
        new = str(d.get("new_status") or "").strip()
        vendor = str(d.get("vendor") or "").strip()
        amount = d.get("amount")
        parts = []
        if vendor:
            parts.append(vendor)
        if amount is not None:
            parts.append(_format_money(amount))
        if prev and new:
            parts.append(f"{prev} → {new}")
        elif new:
            parts.append(new)
        return " — ".join(parts) if parts else "Payment status updated"
    if event == "goods_receipt_recorded":
        po_number = str(d.get("po_number") or "").strip()
        qty = d.get("grn_qty")
        receiver = str(d.get("receiver") or "").strip()
        if po_number and qty is not None:
            label = f"GRN recorded for {po_number} (qty {qty})"
            return f"{label}, receiver {receiver}" if receiver else label
        return "Goods receipt recorded"
    if event == "purchase_variance_approved":
        po_number = str(d.get("po_number") or "").strip()
        match_status = str(d.get("match_status") or "").strip()
        if po_number and match_status:
            return f"Variance approved for {po_number} ({match_status})"
        return "Purchase variance approved"
    if event == "team_expense_auto_approved":
        amount = d.get("amount")
        threshold = d.get("threshold")
        employee = str(d.get("employee_name") or "").strip()
        if amount is not None and threshold is not None:
            base = f"Auto-approved {_format_money(amount)} (below {_format_money(threshold)})"
            return f"{base}, {employee}" if employee else base
        return "Team expense auto-approved"
    if event == "vendor_sender_learned":
        vendor = str(d.get("vendor") or d.get("vendor_slug") or "").strip()
        sender = str(d.get("sender") or "").strip()
        if vendor and sender:
            return f"Learned sender {sender} → {vendor}"
        return "Vendor sender learned"
    if event == "purchase_document_processed":
        doc_type = str(d.get("purchase_document_type") or "").strip()
        return f"Purchase {doc_type} document completed" if doc_type else "Purchase document processed"
    if event == "purchase_awaiting_po":
        po_number = str(d.get("po_number") or "").strip()
        return f"Awaiting PO {po_number}" if po_number else "Purchase awaiting PO"
    if event == "purchase_po_reference_not_required":
        po_number = str(d.get("po_number") or "").strip()
        return (
            f"PO {po_number} noted — not required for document type"
            if po_number
            else "PO reference noted — not required for document type"
        )
    if event == "vendor_registration_released":
        vendor = str(d.get("vendor") or "").strip()
        return f"Hold released for {vendor}" if vendor else "Vendor registration released"
    if event == "accounting_integration_connected":
        label = str(d.get("provider_label") or d.get("provider") or "").strip()
        company = str(d.get("display_name") or "").strip()
        if label and company:
            return f"{label} connected — {company}"
        return f"{label} connected" if label else "Accounting integration connected"
    if event == "accounting_integration_disconnected":
        label = str(d.get("provider_label") or d.get("provider") or "").strip()
        company = str(d.get("display_name") or "").strip()
        if label and company:
            return f"{label} disconnected — {company}"
        return f"{label} disconnected" if label else "Accounting integration disconnected"
    if event == "accounting_integration_error":
        label = str(d.get("provider_label") or d.get("provider") or "").strip()
        reason = truncate_audit_error(str(d.get("reason") or ""))
        if label and reason:
            return f"{label} error — {reason}"
        return reason or "Accounting integration error"
    if event == "journal_control_account_unresolved":
        unresolved = d.get("unresolved")
        prefix = (
            "Rule book remap — "
            if str(d.get("context") or "").strip() == "remap_skip"
            else ""
        )
        if isinstance(unresolved, list) and unresolved:
            return (
                f"{prefix}Unresolved control accounts: "
                f"{', '.join(str(item) for item in unresolved)}"
            )
        return f"{prefix}Control/tax account missing from chart of accounts"
    if event == "journal_unbalanced":
        prefix = (
            "Rule book remap — "
            if str(d.get("context") or "").strip() == "remap_skip"
            else ""
        )
        subtotal = d.get("subtotal")
        gst = d.get("gst")
        total = d.get("total")
        if subtotal is not None and gst is not None and total is not None:
            return (
                f"{prefix}Journal unbalanced — "
                f"subtotal {subtotal}, GST {gst}, total {total}"
            )
        return f"{prefix}Journal debits and credits do not balance"

    reason = str(d.get("hold_reason") or d.get("reason") or "").strip()
    if reason:
        return reason

    rule_type = str(d.get("rule_type") or "").strip()
    match_reason = str(d.get("match_reason") or "").strip()
    if rule_type or match_reason:
        return _summarize_mapping_applied(d)

    return event.replace("_", " ").capitalize()
