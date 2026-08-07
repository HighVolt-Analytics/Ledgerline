"""Automatic Team Expenses claim kind: document type pin, else outstanding advance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.master_data import EmployeeMasterCreate
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    ChartOfAccountEntry,
    PostingDefaults,
    RuleBookConfigPayload,
    TeamExpensePostingDefaults,
    validate_rule_book_config_payload,
)
from app.services.master_data.master_data_service import create_employee_master
from app.services.master_data.party_coa_subledger_service import party_sub_ledger_code
from app.services.purchase.team_expense_kind_service import (
    document_type_team_expense_kind,
    resolve_default_team_expense_kind,
    stamp_team_expense_kind,
)
from app.services.rule_book.rule_book_config_io import (
    load_rule_book_config_dict,
    save_rule_book_config,
)
from app.services.rule_book.rule_book_mapper import ROUTE_PURCHASE, ROUTE_TEAM
from app.tenant_ids import TESTING_TENANT_UUID

EMPLOYEE_ID = "em-marcus"
EMPLOYEE_EMAIL = "marcus@example.com"


def _document_type(code: str, *, team_expense_kind: str = "") -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=f"{code} title",
        short_title=code,
        klass="Transactional",
        posting="Yes",
        route_target=ROUTE_TEAM,
        playbook_profile="employee_claim",
        team_expense_kind=team_expense_kind,
        # Kind-defaulting tests need advance balance auto-pick enabled.
        budget_control=True,
        advance_control=True,
        post_to={"ledger": "Operating Expenses"},
    )


def _config(*document_types: DocumentTypeDefinition) -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        team_expense_posting=TeamExpensePostingDefaults(
            default_advance_parent_ledger="Staff Advance",
            settlement_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1300", name="Staff Advance", type="Asset"),
            ChartOfAccountEntry(code="5000", name="Operating Expenses", type="Expense"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
        document_types=list(document_types),
    )


async def _setup(
    db_session: AsyncSession,
    *document_types: DocumentTypeDefinition,
) -> RuleBookConfigPayload:
    await save_rule_book_config(db_session, _config(*document_types), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id=EMPLOYEE_ID,
            name="Marcus Webb",
            email=EMPLOYEE_EMAIL,
            advance_parent_ledger="Staff Advance",
        ),
    )
    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    return validate_rule_book_config_payload(raw)


async def _claim(
    db_session: AsyncSession,
    *,
    document_type_code: str | None,
    route_target: str = ROUTE_TEAM,
) -> Invoice:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        invoice_date=date(2026, 5, 1),
        total=Decimal("300"),
        route_target=route_target,
        document_type_code=document_type_code,
        email_sender=EMPLOYEE_EMAIL,
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice


async def _post_advance(db_session: AsyncSession, amount: str) -> None:
    """Debit the employee advance child so an outstanding balance exists."""
    invoice = await _claim(db_session, document_type_code=None)
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=invoice.id,
            date=date(2026, 4, 1),
            account_code=party_sub_ledger_code(EMPLOYEE_ID),
            account_name="Marcus Webb",
            debit=Decimal(amount),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()


def test_document_type_kind_reads_pin_and_ignores_auto() -> None:
    assert (
        document_type_team_expense_kind(
            _document_type("DT-20", team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE)
        )
        == TEAM_EXPENSE_KIND_ADVANCE
    )
    assert document_type_team_expense_kind(_document_type("DT-12")) is None
    assert document_type_team_expense_kind(None) is None


def test_title_wins_over_swapped_team_expense_kind_pin() -> None:
    from app.services.purchase.team_expense_kind_service import (
        reconcile_team_expense_kind_for_document_type,
    )

    assert (
        reconcile_team_expense_kind_for_document_type(
            title="Employee expense claim",
            configured=TEAM_EXPENSE_KIND_ADVANCE,
        )
        == TEAM_EXPENSE_KIND_CLAIM
    )
    assert (
        reconcile_team_expense_kind_for_document_type(
            title="Employee advance request",
            configured=TEAM_EXPENSE_KIND_CLAIM,
        )
        == TEAM_EXPENSE_KIND_ADVANCE
    )


@pytest.mark.asyncio
async def test_stamp_heals_swapped_expense_claim_document_type_pin(
    db_session: AsyncSession,
) -> None:
    """DT title says expense claim even if Rules pin was wrongly set to advance."""
    claim_dt = DocumentTypeDefinition(
        code="DT-04",
        title="Employee expense claim",
        short_title="Expense claim",
        klass="Transactional",
        posting="Yes",
        route_target=ROUTE_TEAM,
        playbook_profile="employee_claim",
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        budget_control=True,
        advance_control=True,
        post_to={"ledger": "Operating Expenses"},
    )
    config = await _setup(db_session, claim_dt)
    invoice = await _claim(db_session, document_type_code="DT-04")

    stamped = await stamp_team_expense_kind(db_session, invoice, config)

    assert stamped == TEAM_EXPENSE_KIND_CLAIM
    assert invoice.team_expense_kind == TEAM_EXPENSE_KIND_CLAIM


def test_unknown_document_type_kind_falls_back_to_auto() -> None:
    assert _document_type("DT-12", team_expense_kind="nonsense").team_expense_kind == ""


@pytest.mark.asyncio
async def test_pinned_document_type_wins_over_advance_balance(
    db_session: AsyncSession,
) -> None:
    config = await _setup(
        db_session,
        _document_type("DT-20", team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE),
    )
    await _post_advance(db_session, "1000")
    invoice = await _claim(db_session, document_type_code="DT-20")

    kind = await resolve_default_team_expense_kind(db_session, invoice, config)

    assert kind == TEAM_EXPENSE_KIND_ADVANCE


@pytest.mark.asyncio
async def test_auto_picks_expense_claim_even_when_employee_holds_advance(
    db_session: AsyncSession,
) -> None:
    """Outstanding float no longer switches kind — auto-pick is always claim."""
    config = await _setup(db_session, _document_type("DT-12"))
    await _post_advance(db_session, "1000")
    invoice = await _claim(db_session, document_type_code="DT-12")

    kind = await resolve_default_team_expense_kind(db_session, invoice, config)

    assert kind == TEAM_EXPENSE_KIND_CLAIM


@pytest.mark.asyncio
async def test_auto_picks_expense_claim_without_advance(db_session: AsyncSession) -> None:
    config = await _setup(db_session, _document_type("DT-12"))
    invoice = await _claim(db_session, document_type_code="DT-12")

    kind = await resolve_default_team_expense_kind(db_session, invoice, config)

    assert kind == TEAM_EXPENSE_KIND_CLAIM


@pytest.mark.asyncio
async def test_unknown_sender_defaults_to_expense_claim(db_session: AsyncSession) -> None:
    config = await _setup(db_session, _document_type("DT-12"))
    await _post_advance(db_session, "1000")
    invoice = await _claim(db_session, document_type_code="DT-12")
    invoice.email_sender = "stranger@example.com"

    kind = await resolve_default_team_expense_kind(db_session, invoice, config)

    assert kind == TEAM_EXPENSE_KIND_CLAIM


@pytest.mark.asyncio
async def test_stamp_fills_empty_kind(db_session: AsyncSession) -> None:
    config = await _setup(db_session, _document_type("DT-12"))
    invoice = await _claim(db_session, document_type_code="DT-12")

    stamped = await stamp_team_expense_kind(db_session, invoice, config)

    assert stamped == TEAM_EXPENSE_KIND_CLAIM
    assert invoice.team_expense_kind == TEAM_EXPENSE_KIND_CLAIM


@pytest.mark.asyncio
async def test_stamp_never_overwrites_a_reviewer_choice(db_session: AsyncSession) -> None:
    config = await _setup(db_session, _document_type("DT-12"))
    await _post_advance(db_session, "1000")
    invoice = await _claim(db_session, document_type_code="DT-12")
    invoice.team_expense_kind = TEAM_EXPENSE_KIND_ADVANCE

    stamped = await stamp_team_expense_kind(db_session, invoice, config)

    assert stamped == TEAM_EXPENSE_KIND_ADVANCE
    assert invoice.team_expense_kind == TEAM_EXPENSE_KIND_ADVANCE


@pytest.mark.asyncio
async def test_stamp_skips_documents_off_the_team_route(db_session: AsyncSession) -> None:
    config = await _setup(db_session, _document_type("DT-12"))
    invoice = await _claim(
        db_session,
        document_type_code="DT-12",
        route_target=ROUTE_PURCHASE,
    )

    assert await stamp_team_expense_kind(db_session, invoice, config) is None
    assert invoice.team_expense_kind is None


@pytest.mark.asyncio
async def test_advance_header_mapping_uses_employee_child_not_expense_post_to(
    db_session: AsyncSession,
) -> None:
    from app.services.purchase.team_expense_kind_service import (
        resolve_team_expense_header_mapping,
    )
    from app.services.rule_book.account_mapper import AccountMapping, MappingDetail

    config = await _setup(
        db_session,
        _document_type("DT-09", team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE),
    )
    invoice = await _claim(db_session, document_type_code="DT-09")
    invoice.team_expense_kind = TEAM_EXPENSE_KIND_ADVANCE

    expense = AccountMapping("5000", "Operating Expenses")
    detail = MappingDetail(
        expense_category="Operating Expenses",
        account_code="5000",
        account_name="Operating Expenses",
        rule_type="document_type",
        match_reason="DT-09",
    )
    mapping, mapped_detail = await resolve_team_expense_header_mapping(
        db_session,
        invoice,
        config,
        mapping=expense,
        detail=detail,
    )

    assert mapping.account_code == party_sub_ledger_code(EMPLOYEE_ID)
    assert mapping.account_name == "Marcus Webb"
    assert mapped_detail.rule_type == "team_expense_advance"
    assert mapped_detail.account_name == "Marcus Webb"
