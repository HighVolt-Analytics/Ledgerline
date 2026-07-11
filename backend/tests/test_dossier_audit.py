"""Tests for dossier audit event coverage."""

from app.services.dossier.dossier_audit import DOSSIER_AUDIT_EVENTS
from app.services.dossier.dossier_pipeline_service import PIPELINE_AUDIT_EVENTS
from app.services.invoice.processing_cycle_service import CYCLE_RESET_EVENTS


def test_dossier_audit_events_derived_from_pipeline_stage_map() -> None:
    assert PIPELINE_AUDIT_EVENTS.issubset(DOSSIER_AUDIT_EVENTS)
    assert CYCLE_RESET_EVENTS.issubset(DOSSIER_AUDIT_EVENTS)


def test_dossier_audit_events_include_journal_and_cycle_reset() -> None:
    assert "journal_unbalanced" in DOSSIER_AUDIT_EVENTS
    assert "journal_control_account_unresolved" in DOSSIER_AUDIT_EVENTS
    assert "three_way_match_variance_unapproved" in DOSSIER_AUDIT_EVENTS
    assert "invoice_requeued" in DOSSIER_AUDIT_EVENTS
    assert "invoice_rejected" in DOSSIER_AUDIT_EVENTS
    assert "pipeline_error" in DOSSIER_AUDIT_EVENTS
