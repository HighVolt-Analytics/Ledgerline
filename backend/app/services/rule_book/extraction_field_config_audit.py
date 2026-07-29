"""Warn when document-type extraction_fields omit playbook/route-recommended keys."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.classification.document_type_playbook_profile_service import (
    effective_playbook_profile,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

RECOMMENDED_FIELDS_BY_PLAYBOOK: dict[str, tuple[str, ...]] = {
    "standard_transactional": ("invoice_no", "invoice_date", "vendor", "total"),
    "po_goods": ("invoice_no", "invoice_date", "vendor", "total", "po_reference"),
    "ar_goods": ("invoice_no", "invoice_date", "vendor", "total", "so_reference"),
    "ar_goods_2way": ("invoice_no", "invoice_date", "so_reference"),
    "po_services": ("invoice_no", "invoice_date", "vendor", "total", "po_reference"),
    "direct_expense": ("invoice_no", "invoice_date", "vendor", "total"),
    "credit_adjustment": ("invoice_no", "invoice_date", "vendor"),
    "debit_note": ("invoice_no", "invoice_date", "vendor"),
    "freight_logistics": ("invoice_no", "invoice_date", "vendor", "total"),
    "import_dossier": ("invoice_no", "invoice_date"),
    "employee_claim": ("email_sender", "invoice_date", "total", "vendor", "invoice_no"),
    "intercompany": ("invoice_no", "invoice_date", "vendor", "total"),
    "pre_transactional": ("invoice_no",),
}

RECOMMENDED_FIELDS_BY_ROUTE: dict[str, tuple[str, ...]] = {
    "Purchase Management": ("due_date",),
    "Sales Management": ("due_date",),
    "Expenses Management": ("due_date",),
}

_NON_TRANSACTIONAL_PLAYBOOKS = frozenset(
    {
        "supporting",
        "reconciliation",
        "non_actionable",
        "informational",
        "master_data",
        "compliance_route",
    }
)


def _normalized_extraction_keys(defn: DocumentTypeDefinition) -> set[str]:
    return {str(key or "").strip().lower() for key in (defn.extraction_fields or []) if str(key or "").strip()}


def _recommended_keys(defn: DocumentTypeDefinition) -> set[str]:
    profile = effective_playbook_profile(defn)
    if profile in _NON_TRANSACTIONAL_PLAYBOOKS:
        return set()
    keys: set[str] = set()
    keys.update(RECOMMENDED_FIELDS_BY_PLAYBOOK.get(profile, ()))
    route = (defn.route_target or "").strip()
    route_keys = RECOMMENDED_FIELDS_BY_ROUTE.get(route, ())
    if route_keys and keys & {"total", "subtotal", "gst"}:
        keys.update(route_keys)
    required = {str(key or "").strip().lower() for key in (defn.required_fields or []) if str(key or "").strip()}
    keys.update(required)
    return keys


def audit_document_type_extraction_config(defn: DocumentTypeDefinition) -> list[str]:
    """Human-readable warnings for one document type."""
    if not defn.enabled:
        return []
    configured = _normalized_extraction_keys(defn)
    if not configured:
        return []
    recommended = _recommended_keys(defn)
    missing = sorted(key for key in recommended if key not in configured)
    if not missing:
        return []
    profile = effective_playbook_profile(defn)
    title = (defn.short_title or defn.title or defn.code or "").strip()
    return [
        (
            f"{defn.code} {title}: playbook {profile} recommends "
            f"{', '.join(missing)} in extraction_fields (DI may extract but not persist)"
        )
    ]


def audit_rule_book_extraction_config(payload: RuleBookConfigPayload) -> list[str]:
    warnings: list[str] = []
    for defn in payload.document_types:
        warnings.extend(audit_document_type_extraction_config(defn))
    return warnings


_LOGGED_WARNING_FINGERPRINTS: set[tuple[str, ...]] = set()


def log_extraction_field_config_warnings(payload: RuleBookConfigPayload) -> int:
    """Log warnings once per unique message set (startup/save); return count.

    Request-path config validation must not call this — it floods logs.
    """
    warnings = audit_rule_book_extraction_config(payload)
    if not warnings:
        return 0
    fingerprint = tuple(warnings)
    if fingerprint in _LOGGED_WARNING_FINGERPRINTS:
        return len(warnings)
    _LOGGED_WARNING_FINGERPRINTS.add(fingerprint)
    for message in warnings:
        logger.warning("extraction_field_config_gap", message=message)
    logger.warning(
        "extraction_field_config_audit_summary",
        warning_count=len(warnings),
    )
    return len(warnings)
