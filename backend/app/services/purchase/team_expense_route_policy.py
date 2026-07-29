"""Team Expenses channel policy: employee identity on email/WhatsApp/Viber only.

Manual upload never routes to Team Expenses. A known employee sender on an
allowed capture channel always does (catalogue DT is filled if needed).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import (
    ROUTE_TEAM,
    is_team_expenses_document_type,
    team_expenses_document_types,
)
from app.services.purchase.team_expense_validator import find_employee_by_sender

TEAM_EXPENSE_CAPTURE_CHANNELS = frozenset({"email", "whatsapp", "viber"})


def normalize_capture_source(invoice: Any) -> str:
    """Resolve ingest channel; unset + no connection markers → upload."""
    capture = (getattr(invoice, "capture_source", None) or "").strip().lower()
    if capture in TEAM_EXPENSE_CAPTURE_CHANNELS or capture == "upload":
        return capture
    if getattr(invoice, "connected_mailbox_id", None) is not None:
        return "email"
    if getattr(invoice, "whatsapp_connection_id", None) is not None:
        return "whatsapp"
    if getattr(invoice, "viber_connection_id", None) is not None:
        return "viber"
    return "upload"


def team_expenses_allowed_capture(capture_source: str | None) -> bool:
    src = (capture_source or "").strip().lower()
    if src in TEAM_EXPENSE_CAPTURE_CHANNELS:
        return True
    return False


def should_force_team_expenses(invoice: Any, employees: Sequence[Any] | None) -> bool:
    """True when channel allows TE and sender matches employee registry."""
    if not team_expenses_allowed_capture(normalize_capture_source(invoice)):
        return False
    sender = getattr(invoice, "email_sender", None)
    return find_employee_by_sender(list(employees or []), sender) is not None


def primary_team_expenses_document_type(
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition | None:
    rows = team_expenses_document_types(document_types)
    return rows[0] if rows else None


def ensure_team_expenses_document_type(
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition | None:
    """If invoice DT is not a TE type, assign the catalogue primary TE DT."""
    code = (getattr(invoice, "document_type_code", None) or "").strip().upper()
    current = None
    if code and document_types:
        for dt in document_types:
            if (dt.code or "").strip().upper() == code:
                current = dt
                break
    if is_team_expenses_document_type(current):
        return current
    primary = primary_team_expenses_document_type(document_types)
    if primary is None:
        return None
    invoice.document_type_code = (primary.code or "").strip().upper()
    if getattr(invoice, "document_type_confidence", None) is None or float(
        invoice.document_type_confidence or 0.0
    ) < 0.9:
        invoice.document_type_confidence = 0.95
    return primary


def team_expenses_blocked_for_upload(invoice: Any) -> bool:
    """True when capture is upload (TE must not be assigned)."""
    return normalize_capture_source(invoice) == "upload"
