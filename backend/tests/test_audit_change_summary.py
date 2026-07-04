"""Audit change summary for CSV export."""

from app.services.audit.audit_change_summary import summarize_audit_change


def test_rule_book_updated_modified_rule() -> None:
    summary = summarize_audit_change(
        "rule_book_updated",
        {
            "changes": {
                "email_capture_rules": {
                    "added": [],
                    "removed": [],
                    "modified": ["ec-1"],
                }
            }
        },
    )
    assert summary == "Rule ec-1 modified"


def test_rule_book_updated_rule_added() -> None:
    summary = summarize_audit_change(
        "rule_book_updated",
        {
            "changes": {
                "email_capture_rules": {
                    "added": ["ec-9"],
                    "removed": [],
                    "modified": [],
                }
            }
        },
    )
    assert summary == "1 rule added to email_capture_rules"


def test_unmatched_expense_vendor_summary() -> None:
    summary = summarize_audit_change(
        "unmatched_expense_vendor",
        {
            "vendor_confidence": 0.0,
            "threshold": 70,
            "amount": 189,
            "hold_above": 500,
        },
    )
    assert summary == (
        "Vendor confidence: 0.0, below threshold 70, amount $189 under hold limit $500"
    )


def test_purchase_invoice_sync_summary() -> None:
    summary = summarize_audit_change(
        "purchase_invoice_document_synced",
        {"po_number": "PO-MKT-2026-014"},
    )
    assert summary == "PO-MKT-2026-014 invoice linked"


def test_reconciliation_skipped_summary() -> None:
    summary = summarize_audit_change(
        "reconciliation_skipped",
        {"reason": "RC1: invoice totals 768.50 != AP credits 268.50"},
    )
    assert summary == "RC1: invoice totals 768.50 != AP credits 268.50"


def test_email_moved_summary() -> None:
    summary = summarize_audit_change(
        "email_moved",
        {
            "folder": "Processed",
            "reason": "invoice_processed",
            "outcome": "processed",
        },
    )
    assert summary == "Moved to Processed: invoice_processed"


def test_ingest_capture_summary() -> None:
    summary = summarize_audit_change(
        "ingest_capture_matched",
        {
            "rule_name": "Expense test PDF",
            "attachment": "test-expense-telstra.pdf",
            "ingest_only": True,
        },
    )
    assert "Ingestion rule matched" in summary
    assert "Expense test PDF" in summary


def test_duplicate_skipped_summary() -> None:
    summary = summarize_audit_change(
        "duplicate_skipped",
        {
            "original_invoice_id": 42,
            "filename": "invoice.pdf",
            "source": "email",
        },
    )
    assert "Duplicate file skipped" in summary
    assert "42" in summary
    assert "invoice.pdf" in summary


def test_duplicate_in_progress_summary() -> None:
    summary = summarize_audit_change(
        "duplicate_in_progress",
        {"filename": "receipt.pdf", "source": "whatsapp"},
    )
    assert "Duplicate blocked" in summary
    assert "receipt.pdf" in summary


def test_validation_failed_from_invoice_results() -> None:
    summary = summarize_audit_change(
        "validation_failed",
        None,
        validation_results_json='[{"rule": "VR03", "passed": false, "message": "missing line items"}]',
    )
    assert summary == "Failed checks: VR03"
