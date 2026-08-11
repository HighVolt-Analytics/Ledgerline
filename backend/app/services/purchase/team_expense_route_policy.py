"""Team Expenses channel policy: employee identity on email/WhatsApp/Viber only.

Manual upload never routes to Team Expenses. A known employee sender on an
allowed capture channel always does (catalogue DT is filled if needed).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
)
from app.services.classification.document_type_catalog import (
    ROUTE_TEAM,
    is_team_expenses_document_type,
    team_expenses_document_types,
)
from app.services.purchase.team_expense_validator import find_employee_by_sender

TEAM_EXPENSE_CAPTURE_CHANNELS = frozenset({"email", "whatsapp", "viber"})
_PINNED_ADVANCE_KINDS = frozenset({TEAM_EXPENSE_KIND_ADVANCE})


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


def infer_preferred_team_expense_kind(
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
) -> str | None:
    """Best claim-kind hint from invoice state / catalogue title / LLM suggestion."""
    from app.services.classification.catalogue_title_match import (
        match_catalogue_dt_by_vision_title,
    )
    from app.services.purchase.team_expense_kind_service import (
        document_type_team_expense_kind,
    )

    existing = (getattr(invoice, "team_expense_kind", None) or "").strip().lower()
    if existing in _PINNED_ADVANCE_KINDS:
        return existing

    heading = (getattr(invoice, "document_heading", None) or "").strip()
    if heading and document_types:
        title_hit = match_catalogue_dt_by_vision_title(
            document_heading=heading,
            document_types=document_types,
        )
        if title_hit is not None:
            pinned = document_type_team_expense_kind(title_hit[0])
            if pinned:
                return pinned

    # Last resort: catalogue TE rows matched by title/summary phrases already on
    # those rows (not a global English dictionary). Prefer LLM-suggested TE code.
    llm_code = (getattr(invoice, "llm_suggested_dt", None) or "").strip().upper()
    if llm_code and document_types:
        for row in document_types:
            if (row.code or "").strip().upper() != llm_code:
                continue
            pinned = document_type_team_expense_kind(row)
            if pinned in _PINNED_ADVANCE_KINDS or pinned:
                return pinned
            break

    if existing:
        return existing
    return None


def primary_team_expenses_document_type(
    document_types: Sequence[DocumentTypeDefinition] | None,
    *,
    preferred_kind: str | None = None,
    preferred_code: str | None = None,
) -> DocumentTypeDefinition | None:
    rows = team_expenses_document_types(document_types)
    if not rows:
        return None

    code = (preferred_code or "").strip().upper()
    if code:
        for row in rows:
            if (row.code or "").strip().upper() == code:
                return row

    kind = (preferred_kind or "").strip().lower()
    if kind:
        from app.services.purchase.team_expense_kind_service import (
            document_type_team_expense_kind,
        )

        for row in rows:
            pinned = document_type_team_expense_kind(row)
            if pinned and pinned == kind:
                return row
    return rows[0]


def ensure_team_expenses_document_type(
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition] | None,
    *,
    preferred_kind: str | None = None,
) -> DocumentTypeDefinition | None:
    """If invoice DT is not a TE type, assign the best matching catalogue TE DT.

    Prefer (in order): current TE DT, LLM-suggested TE code, kind inferred from
    heading/kind pin, then catalogue primary. Never replace a TE DT that already
    pins advance_requisition with a generic claim DT.
    """
    from app.services.purchase.team_expense_kind_service import (
        document_type_team_expense_kind,
    )

    code = (getattr(invoice, "document_type_code", None) or "").strip().upper()
    current = None
    if code and document_types:
        for dt in document_types:
            if (dt.code or "").strip().upper() == code:
                current = dt
                break
    if is_team_expenses_document_type(current):
        current_kind = document_type_team_expense_kind(current)
        # Keep a specific advance DT even if a later force-TE pass prefers primary.
        if current_kind in _PINNED_ADVANCE_KINDS:
            return current
        preferred = preferred_kind or infer_preferred_team_expense_kind(
            invoice, document_types
        )
        if preferred in _PINNED_ADVANCE_KINDS:
            better = primary_team_expenses_document_type(
                document_types,
                preferred_kind=preferred,
                preferred_code=(getattr(invoice, "llm_suggested_dt", None) or ""),
            )
            if better is not None and document_type_team_expense_kind(better) == preferred:
                invoice.document_type_code = (better.code or "").strip().upper()
                if getattr(invoice, "document_type_confidence", None) is None or float(
                    invoice.document_type_confidence or 0.0
                ) < 0.9:
                    invoice.document_type_confidence = 0.95
                return better
        return current

    kind = preferred_kind or infer_preferred_team_expense_kind(invoice, document_types)
    preferred_code = (getattr(invoice, "llm_suggested_dt", None) or "").strip().upper()
    primary = primary_team_expenses_document_type(
        document_types,
        preferred_kind=kind,
        preferred_code=preferred_code,
    )
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
