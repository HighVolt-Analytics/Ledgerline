"""Team Expenses channel policy: employee identity on messaging + employee upload.



Email / WhatsApp / Viber: known employee sender forces Team Expenses unless the

document looks commercial (PO / SO / credit note).

Upload: same force when the signed-in uploader (or stamped employee_email) matches

the employee registry, or when an explicit claim/advance intent is pinned.

Slack never routes to Team Expenses. Vendor-invoice intent keeps upload on AP.

Employee-matrix membership is monitoring context, not a classification gate.

"""



from __future__ import annotations



from collections.abc import Sequence

from typing import Any



from app.schemas.document_type import DocumentTypeDefinition

from app.schemas.rule_book_config import (

    TEAM_EXPENSE_KIND_ADVANCE,

    TEAM_EXPENSE_KIND_CLAIM,

)

from app.services.classification.document_type_catalog import (

    ROUTE_TEAM,

    is_team_expenses_document_type,

    team_expenses_document_types,

)

from app.services.purchase.team_expense_validator import find_employee_by_sender



TEAM_EXPENSE_CAPTURE_CHANNELS = frozenset({"email", "whatsapp", "viber"})

# Mobile / upload intent query values (also stored on extracted_fields).
TEAM_EXPENSE_INTENT_CLAIM = TEAM_EXPENSE_KIND_CLAIM
TEAM_EXPENSE_INTENT_ADVANCE = TEAM_EXPENSE_KIND_ADVANCE
TEAM_EXPENSE_INTENT_VENDOR = "vendor_invoice"
TEAM_EXPENSE_TE_INTENTS = frozenset(
    {TEAM_EXPENSE_INTENT_CLAIM, TEAM_EXPENSE_INTENT_ADVANCE}
)

_PINNED_ADVANCE_KINDS = frozenset({TEAM_EXPENSE_KIND_ADVANCE})





def normalize_capture_source(invoice: Any) -> str:

    """Resolve ingest channel; unset + no connection markers → upload."""

    capture = (getattr(invoice, "capture_source", None) or "").strip().lower()

    if capture in {"app", "mobile", "mob"}:

        return "app"

    if capture in TEAM_EXPENSE_CAPTURE_CHANNELS or capture in {"upload", "slack"}:

        return capture

    if getattr(invoice, "connected_mailbox_id", None) is not None:

        return "email"

    if getattr(invoice, "whatsapp_connection_id", None) is not None:

        return "whatsapp"

    if getattr(invoice, "viber_connection_id", None) is not None:

        return "viber"

    if getattr(invoice, "slack_connection_id", None) is not None:

        return "slack"

    return "upload"





def pinned_team_expense_intent(invoice: Any | None) -> str | None:
    """Normalize upload/mobile intent from extracted_fields or team_expense_kind pin."""
    if invoice is None:
        return None
    fields = getattr(invoice, "extracted_fields", None) or {}
    if isinstance(fields, dict):
        raw = str(fields.get("team_expense_intent") or "").strip().lower()
        if raw in TEAM_EXPENSE_TE_INTENTS or raw == TEAM_EXPENSE_INTENT_VENDOR:
            return raw
    kind = (getattr(invoice, "team_expense_kind", None) or "").strip().lower()
    if kind in TEAM_EXPENSE_TE_INTENTS:
        return kind
    return None


def employee_identity_for_te(invoice: Any | None) -> str | None:
    """Best email identity for TE employee matching (upload stamps uploaded_by)."""
    if invoice is None:
        return None
    for attr in ("employee_email", "uploaded_by_email", "email_sender"):
        value = getattr(invoice, attr, None)
        if value and str(value).strip():
            return str(value).strip()
    return None


def team_expenses_allowed_capture(
    capture_source: str | None,
    *,
    invoice: Any | None = None,
    employees: Sequence[Any] | None = None,
) -> bool:
    """True when this channel may keep a Team Expenses route.

    Messaging channels are always eligible (identity checked in should_force).
    Upload is eligible only when the uploader/employee identity matches the
    registry, or an explicit claim/advance intent is pinned for a known employee.
    Slack is never eligible.
    """
    src = (capture_source or "").strip().lower()
    if src in {"app", "mobile", "mob"}:
        src = "app"
    if src in TEAM_EXPENSE_CAPTURE_CHANNELS:
        return True
    if src not in {"upload", "app"}:
        return False
    intent = pinned_team_expense_intent(invoice)
    if intent == TEAM_EXPENSE_INTENT_VENDOR:
        return False
    emp_list = list(employees or [])
    identity = employee_identity_for_te(invoice)
    matched = find_employee_by_sender(emp_list, identity) is not None
    if not matched:
        return False
    return True





def should_force_team_expenses(invoice: Any, employees: Sequence[Any] | None) -> bool:

    """True when channel allows TE and employee identity matches the registry."""

    channel = normalize_capture_source(invoice)
    if channel == "slack":
        return False

    intent = pinned_team_expense_intent(invoice)
    if intent == TEAM_EXPENSE_INTENT_VENDOR:
        return False

    emp_list = list(employees or [])
    identity = employee_identity_for_te(invoice)
    if find_employee_by_sender(emp_list, identity) is None:
        return False

    if channel in {"upload", "app"}:
        return team_expenses_allowed_capture(
            channel, invoice=invoice, employees=emp_list
        )

    if channel not in TEAM_EXPENSE_CAPTURE_CHANNELS:
        return False

    return True


# Content-based commercial structure. Invoice/receipt numbers alone are not
# commercial — retail claims often have a receipt no.
_COMMERCIAL_ROLE_HINT_KEYS = ("has_po_reference", "has_so_reference", "is_credit_note")


def _hint_is_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def invoice_role_hints(invoice: Any | None) -> dict[str, str]:
    if invoice is None:
        return {}
    from app.services.invoice.vision_type_suggest import document_role_hints_from_invoice

    return document_role_hints_from_invoice(invoice)


def commercial_role_hint_keys(hints: dict[str, str] | None) -> list[str]:
    if not isinstance(hints, dict):
        return []
    return [key for key in _COMMERCIAL_ROLE_HINT_KEYS if _hint_is_true(hints.get(key))]


def role_hints_look_commercial(hints: dict[str, str] | None) -> bool:
    """True when the document has PO / SO / credit-note structure.

    Empty or unknown hints are not commercial — fail toward current TE force.
    ``has_invoice_number`` alone is not commercial.
    """
    return bool(commercial_role_hint_keys(hints))


def should_apply_employee_channel_te_force(
    invoice: Any,
    employees: Sequence[Any] | None,
    *,
    force_team_expenses: bool | None = None,
) -> bool:
    """Channel+employee match, unless document content looks commercial.

    ``should_force_team_expenses`` is identity/channel only. Role hints are the
    authoritative skip. Employee-matrix membership is never a hard gate.

    Explicit claim/advance upload intent wins over commercial role hints so
    mobile employees can pin advance/claim forms that OCR mislabels.

    ``force_team_expenses`` is the DT-map explicit override (same meaning as
    ``_resolve_force_team_expenses``): True/False short-circuits identity lookup.
    """
    if force_team_expenses is False:
        return False
    intent = pinned_team_expense_intent(invoice)
    if intent == TEAM_EXPENSE_INTENT_VENDOR:
        return False
    channel = (
        bool(force_team_expenses)
        if force_team_expenses is not None
        else should_force_team_expenses(invoice, employees)
    )
    if not channel:
        return False
    if intent in TEAM_EXPENSE_TE_INTENTS:
        return True
    return not role_hints_look_commercial(invoice_role_hints(invoice))


def invoice_catalogue_title_match_code(

    invoice: Any,

    document_types: Sequence[DocumentTypeDefinition] | None,

) -> str | None:

    """Catalogue DT code that wins a confident vision title match, if any."""

    heading = (getattr(invoice, "document_heading", None) or "").strip()

    if not heading or not document_types:

        return None

    from app.services.classification.catalogue_title_match import (

        match_catalogue_dt_by_vision_title,

    )



    hit = match_catalogue_dt_by_vision_title(

        document_heading=heading,

        document_types=document_types,

    )

    if hit is None:

        return None

    return (hit[0].code or "").strip().upper() or None





def invoice_has_confident_catalogue_title_match(

    invoice: Any,

    document_types: Sequence[DocumentTypeDefinition] | None,

) -> bool:

    """True when the invoice DT equals the catalogue title-match winner."""

    current = (getattr(invoice, "document_type_code", None) or "").strip().upper()

    if not current:

        return False

    title_match_code = invoice_catalogue_title_match_code(invoice, document_types)

    return bool(title_match_code and current == title_match_code)





def apply_employee_channel_team_expenses_route(

    invoice: Any,

    document_types: Sequence[DocumentTypeDefinition] | None,

    employees: Sequence[Any] | None,

) -> None:

    """Route known employee channels to Team Expenses without clobbering title-match DT.

    Skips when role hints look commercial so a later posting/eval pass cannot
    undo a content-based TE skip.
    """

    if not should_apply_employee_channel_te_force(invoice, employees):

        return

    invoice.route_target = ROUTE_TEAM

    if invoice_has_confident_catalogue_title_match(invoice, document_types):

        return

    current = (getattr(invoice, "document_type_code", None) or "").strip().upper()

    if not current:

        ensure_team_expenses_document_type(

            invoice, document_types, preferred_kind=TEAM_EXPENSE_KIND_CLAIM

        )

        return

    ensure_team_expenses_document_type(invoice, document_types)





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

        infer_team_expense_kind_from_labels,

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

    fields = getattr(invoice, "extracted_fields", None) or {}

    canonical = ""

    if isinstance(fields, dict):

        canonical = str(fields.get("canonical_document_type") or "").strip()

    inferred = infer_team_expense_kind_from_labels(heading, canonical)

    if inferred:

        return inferred

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

    return None





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



    if invoice_has_confident_catalogue_title_match(invoice, document_types):

        code = (getattr(invoice, "document_type_code", None) or "").strip().upper()

        if code and document_types:

            for dt in document_types:

                if (dt.code or "").strip().upper() == code:

                    return dt

        return None



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

    """True when TE catalogue rows must be dropped for this upload/Slack row.

    Slack always blocks. Upload blocks unless a known-employee TE path applies
    (stamped identity + optional claim/advance intent). Vendor intent always blocks.
    When ``force_team_expenses`` is already true upstream, the DT pool keeps TE
    rows regardless of this helper.
    """

    channel = normalize_capture_source(invoice)
    if channel == "slack":
        return True
    if channel != "upload":
        return False
    intent = pinned_team_expense_intent(invoice)
    if intent == TEAM_EXPENSE_INTENT_VENDOR:
        return True
    if intent in TEAM_EXPENSE_TE_INTENTS:
        # Intent pin: keep TE in the pool; identity is enforced in should_force.
        return False
    # Without explicit TE intent, keep legacy upload block. Employee force still
    # bypasses via force_team_expenses in the DT mapper.
    return True


