"""Post DT-extract rematch — flip org DT once when link signals change the winner."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import (
    get_document_type_definition,
    is_team_expenses_document_type,
)
from app.services.classification.document_type_playbook_profile_service import (
    effective_playbook_profile,
)
from app.services.classification.document_type_rule_engine import (
    _definition_requires_po_reference,
    effective_signals_mode_definition,
)
from app.services.invoice.vision_document_type_map import (
    VisionDocumentTypeMapResult,
    map_vision_via_configured_classifiers,
)


def _effective_definition(
    code: str | None,
    document_types: Sequence[DocumentTypeDefinition],
) -> DocumentTypeDefinition | None:
    token = (code or "").strip().upper()
    if not token:
        return None
    defn = get_document_type_definition(token, document_types=list(document_types))
    if defn is None:
        return None
    return effective_signals_mode_definition(defn) or defn


def definition_requires_po(
    code: str | None,
    document_types: Sequence[DocumentTypeDefinition],
) -> bool:
    defn = _effective_definition(code, document_types)
    if defn is None:
        return False
    return _definition_requires_po_reference(defn)


def definition_playbook_profile(
    code: str | None,
    document_types: Sequence[DocumentTypeDefinition],
) -> str:
    defn = get_document_type_definition(
        (code or "").strip().upper(), document_types=list(document_types)
    )
    if defn is None:
        return ""
    return (effective_playbook_profile(defn) or "").strip().lower()


def _definition_for_code(
    code: str | None,
    document_types: Sequence[DocumentTypeDefinition],
) -> DocumentTypeDefinition | None:
    token = (code or "").strip().upper()
    if not token:
        return None
    return get_document_type_definition(token, document_types=list(document_types))


def link_signal_justifies_dt_flip(
    *,
    current_code: str,
    rematch_code: str,
    document_types: Sequence[DocumentTypeDefinition],
) -> bool:
    """True when rematch differs in PO requirement or playbook family.

    Never demote an already-mapped Team Expenses DT to a non-TE type. Classifier
    rematch uses the full catalogue (no TE claim-evidence pool), so employee
    advance / against-advance forms otherwise flip to generic Expense Claim and
    lose Team Expenses routing before force-TE can run.

    Also never rewrite a DT that pins advance_requisition / expense_against_advance
    to a different claim kind (e.g. DT-10 → DT-08 expense_claim) — both may be TE.
    """
    current = (current_code or "").strip().upper()
    rematch = (rematch_code or "").strip().upper()
    if not current or not rematch or current == rematch:
        return False
    current_defn = _definition_for_code(current, document_types)
    rematch_defn = _definition_for_code(rematch, document_types)
    if is_team_expenses_document_type(current_defn) and not is_team_expenses_document_type(
        rematch_defn
    ):
        return False

    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    )
    from app.services.purchase.team_expense_kind_service import (
        document_type_team_expense_kind,
    )

    current_kind = document_type_team_expense_kind(current_defn)
    rematch_kind = document_type_team_expense_kind(rematch_defn)
    if (
        current_kind
        in {TEAM_EXPENSE_KIND_ADVANCE, TEAM_EXPENSE_KIND_AGAINST_ADVANCE}
        and rematch_kind != current_kind
    ):
        return False

    # TE siblings often differ only by playbook (e.g. DT-10 standard_transactional vs
    # DT-08 employee_claim). Classifier rematch has no TE claim-evidence pool, so a
    # playbook-only TE→TE flip would clobber LLM against-advance / advance picks.
    both_team = is_team_expenses_document_type(
        current_defn
    ) and is_team_expenses_document_type(rematch_defn)
    po_differs = definition_requires_po(current, document_types) != definition_requires_po(
        rematch, document_types
    )
    if both_team and not po_differs:
        return False

    if po_differs:
        return True
    if definition_playbook_profile(current, document_types) != definition_playbook_profile(
        rematch, document_types
    ):
        return True
    return False


def rematch_document_type_after_extract(
    *,
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition],
    heading_kind: str | None,
    current_code: str,
) -> VisionDocumentTypeMapResult | None:
    """Classifier rematch using post-extract fields. None when no flip justified."""
    from app.services.purchase.po_reference import ensure_invoice_po_reference
    from app.services.sales.so_reference import ensure_invoice_so_reference

    ensure_invoice_po_reference(invoice)
    ensure_invoice_so_reference(invoice)

    rematch = map_vision_via_configured_classifiers(
        invoice=invoice,
        document_types=list(document_types),
        heading_kind=heading_kind,
        rule_fail_reason="post_extract_reaffirm",
    )
    if rematch.reason != "classifier_matched" or not rematch.code:
        return None
    if not link_signal_justifies_dt_flip(
        current_code=current_code,
        rematch_code=rematch.code,
        document_types=document_types,
    ):
        return None
    return rematch
