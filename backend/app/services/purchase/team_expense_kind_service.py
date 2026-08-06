"""Default the Team Expenses claim kind so reviewers rarely have to pick one by hand."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    RuleBookConfigPayload,
    TeamExpenseKind,
    normalize_team_expense_kind,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.rule_book.account_mapper import AccountMapping, MappingDetail


def document_type_team_expense_kind(
    definition: DocumentTypeDefinition | None,
) -> TeamExpenseKind | None:
    """Claim kind pinned on the document type, or None when it is left on auto."""
    if definition is None:
        return None
    configured = (getattr(definition, "team_expense_kind", "") or "").strip()
    if not configured:
        return None
    return normalize_team_expense_kind(configured)


async def resolve_default_team_expense_kind(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> TeamExpenseKind:
    """Claim kind to stamp on a new Team Expenses claim.

    A document type that pins a kind wins (advance requisition vs expense claim).
    Otherwise default to expense claim — float balance no longer switches kinds.
    """
    _ = session
    pinned = document_type_team_expense_kind(
        definition if definition is not None else _definition_for_invoice(invoice, config)
    )
    if pinned is not None:
        return pinned
    return TEAM_EXPENSE_KIND_CLAIM


async def stamp_team_expense_kind(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> TeamExpenseKind | None:
    """Fill the claim kind; DT-pinned kind always wins over a stale prior stamp."""
    if (invoice.route_target or "").strip() != ROUTE_TEAM:
        return None

    defn = definition if definition is not None else _definition_for_invoice(invoice, config)
    pinned = document_type_team_expense_kind(defn)
    if pinned is not None:
        invoice.team_expense_kind = pinned
        return pinned

    if (invoice.team_expense_kind or "").strip():
        # Coerce legacy against-advance (and any unknown) onto supported kinds.
        kind = normalize_team_expense_kind(invoice.team_expense_kind)
        invoice.team_expense_kind = kind
        return kind

    kind = await resolve_default_team_expense_kind(
        session,
        invoice,
        config,
        definition=defn,
    )
    invoice.team_expense_kind = kind
    return kind


async def resolve_team_expense_header_mapping(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    mapping: AccountMapping,
    detail: MappingDetail,
) -> tuple[AccountMapping, MappingDetail]:
    """TE header GL: Document Type Post to = parent wallet; content picks Sub later.

    Advance requisitions stamp the employee advance child — not expense Post to.
    Claims keep the DT parent mapping; ``apply_line_gl_mapping`` stamps the Sub-GL
    from document content (platform prompt ``llm.sub_ledger.assign.system``).
    """
    if (invoice.route_target or "").strip() != ROUTE_TEAM:
        return mapping, detail
    if normalize_team_expense_kind(invoice.team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        from app.services.master_data.party_coa_subledger_service import (
            resolve_employee_advance_mapping,
        )

        advance = await resolve_employee_advance_mapping(session, invoice, config)
        return advance, MappingDetail(
            expense_category=advance.expense_category or advance.account_name,
            account_code=advance.account_code,
            account_name=advance.account_name,
            rule_type="team_expense_advance",
            match_reason="Advance requisition: employee advance sub-ledger",
        )

    # Expense claims: keep Document Type parent GL (budget wallet).
    return mapping, detail


def _definition_for_invoice(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> DocumentTypeDefinition | None:
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return None
    for definition in config.document_types:
        if (definition.code or "").strip().upper() == code:
            return definition
    return None
