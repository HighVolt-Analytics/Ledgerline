"""Employee advance sub-ledger creation and outstanding balance checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.master_data import EmployeeMasterCreate, EmployeeMasterUpdate
from app.schemas.rule_book_config import (
    ChartOfAccountEntry,
    PostingDefaults,
    RuleBookConfigPayload,
    TeamExpensePostingDefaults,
    validate_rule_book_config_payload,
)
from app.services.master_data.master_data_service import (
    create_employee_master,
    list_employee_masters,
    update_employee_master,
)
from app.services.master_data.party_coa_subledger_service import (
    party_sub_ledger_code,
    resolve_party_child_mapping,
)
from app.services.purchase.team_expense_advance_service import (
    employee_advance_balance,
    employee_advance_balances_by_ids,
    employee_available_advance,
    pending_against_advance_total,
)
from app.services.purchase.team_expense_approval import assert_team_expense_approvable
from app.services.purchase.team_expense_validator import vr_te07_advance_balance
from app.services.rule_book.rule_book_config_io import (
    load_rule_book_config_dict,
    save_rule_book_config,
)
from app.services.rule_book.rule_book_mapper import ROUTE_TEAM
from app.tenant_ids import TESTING_TENANT_UUID


def _config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        team_expense_posting=TeamExpensePostingDefaults(
            default_advance_parent_ledger="Staff Advance",
            settlement_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1300", name="Staff Advance", type="Asset"),
            ChartOfAccountEntry(code="1350", name="Director Advance", type="Asset"),
            ChartOfAccountEntry(code="1400", name="Tax Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )


async def _reload(db_session: AsyncSession) -> RuleBookConfigPayload:
    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    return validate_rule_book_config_payload(raw)


@pytest.mark.asyncio
async def test_creating_employee_adds_sub_ledger_under_selected_parent(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)

    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-marcus",
            name="Marcus Webb",
            email="marcus@example.com",
            advance_parent_ledger="Staff Advance",
        ),
    )

    assert employee.advance_sub_ledger == "Marcus Webb"
    config = await _reload(db_session)
    child = resolve_party_child_mapping(
        config,
        parent_ledger_name="Staff Advance",
        slug="em-marcus",
    )
    assert child is not None
    assert child.account_code == party_sub_ledger_code("em-marcus")


@pytest.mark.asyncio
async def test_changing_parent_creates_child_under_new_parent(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-priya",
            name="Priya Sharma",
            advance_parent_ledger="Staff Advance",
        ),
    )

    await update_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        "em-priya",
        EmployeeMasterUpdate(advance_parent_ledger="Director Advance"),
    )

    config = await _reload(db_session)
    assert (
        resolve_party_child_mapping(
            config, parent_ledger_name="Director Advance", slug="em-priya"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_employee_without_parent_falls_back_to_team_default(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)

    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(master_id="em-lee", name="Lee Chan"),
    )

    assert employee.advance_sub_ledger == "Lee Chan"
    config = await _reload(db_session)
    assert (
        resolve_party_child_mapping(
            config, parent_ledger_name="Staff Advance", slug="em-lee"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_advance_balance_nets_debits_against_credits(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-marcus",
            name="Marcus Webb",
            advance_parent_ledger="Staff Advance",
        ),
    )
    config = await _reload(db_session)
    code = party_sub_ledger_code("em-marcus")

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        invoice_date=date(2026, 4, 1),
        total=Decimal("1000"),
        route_target=ROUTE_TEAM,
    )
    db_session.add(invoice)
    await db_session.flush()

    db_session.add_all(
        [
            JournalEntry(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=invoice.id,
                date=date(2026, 4, 1),
                account_code=code,
                account_name="Marcus Webb",
                debit=Decimal("1000"),
                credit=Decimal("0"),
                entry_type=EntryType.DEBIT,
            ),
            JournalEntry(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=invoice.id,
                date=date(2026, 4, 5),
                account_code=code,
                account_name="Marcus Webb",
                debit=Decimal("0"),
                credit=Decimal("400"),
                entry_type=EntryType.CREDIT,
            ),
        ]
    )
    await db_session.flush()

    balance = await employee_advance_balance(
        db_session,
        TESTING_TENANT_UUID,
        config,
        employee_id="em-marcus",
        employee_parent_ledger="Staff Advance",
    )
    assert balance == Decimal("600")


@pytest.mark.asyncio
async def test_batch_balances_and_list_response_include_advance(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-marcus",
            name="Marcus Webb",
            email="marcus@example.com",
            advance_parent_ledger="Staff Advance",
        ),
    )
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-lee",
            name="Lee Chan",
            email="lee@example.com",
            advance_parent_ledger="Staff Advance",
        ),
    )
    config = await _reload(db_session)
    code = party_sub_ledger_code("em-marcus")
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        invoice_date=date(2026, 4, 1),
        total=Decimal("500"),
        route_target=ROUTE_TEAM,
    )
    db_session.add(invoice)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=invoice.id,
            date=date(2026, 4, 1),
            account_code=code,
            account_name="Marcus Webb",
            debit=Decimal("500"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    employees = await list_employee_masters(db_session, TESTING_TENANT_UUID)
    by_id = {e.id: e for e in employees}
    assert by_id["em-marcus"].advance_balance == 500.0
    assert by_id["em-lee"].advance_balance == 0.0

    batch = await employee_advance_balances_by_ids(
        db_session, TESTING_TENANT_UUID, config, employees
    )
    assert batch["em-marcus"] == Decimal("500")
    assert batch["em-lee"] == Decimal("0")


@pytest.mark.asyncio
async def test_pending_against_advance_reduces_available(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-marcus",
            name="Marcus Webb",
            email="marcus@example.com",
            advance_parent_ledger="Staff Advance",
        ),
    )
    config = await _reload(db_session)
    code = party_sub_ledger_code("em-marcus")

    advance_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        invoice_date=date(2026, 4, 1),
        total=Decimal("1000"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="advance_requisition",
    )
    pending_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        invoice_date=date(2026, 4, 2),
        total=Decimal("400"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="expense_against_advance",
    )
    current_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        invoice_date=date(2026, 4, 3),
        total=Decimal("700"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="expense_against_advance",
    )
    db_session.add_all([advance_inv, pending_inv, current_inv])
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=advance_inv.id,
            date=date(2026, 4, 1),
            account_code=code,
            account_name="Marcus Webb",
            debit=Decimal("1000"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    pending = await pending_against_advance_total(
        db_session,
        TESTING_TENANT_UUID,
        employee,
        exclude_invoice_id=current_inv.id,
    )
    assert pending == Decimal("400")

    available, ledger, reserved = await employee_available_advance(
        db_session,
        TESTING_TENANT_UUID,
        config,
        employee,
        exclude_invoice_id=current_inv.id,
    )
    assert ledger == Decimal("1000")
    assert reserved == Decimal("400")
    assert available == Decimal("600")

    result = vr_te07_advance_balance(
        employee,
        700.0,
        team_expense_kind="expense_against_advance",
        advance_balance=float(available),
        ledger_balance=float(ledger),
        pending_reserved=float(reserved),
    )
    assert result.passed is False
    assert "exceeds available advance" in result.message
    assert "pending other claims" in result.message


@pytest.mark.asyncio
async def test_approve_recheck_blocks_over_clear(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id="em-marcus",
            name="Marcus Webb",
            email="marcus@example.com",
            advance_parent_ledger="Staff Advance",
        ),
    )
    code = party_sub_ledger_code("em-marcus")
    advance_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        invoice_date=date(2026, 4, 1),
        total=Decimal("500"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="advance_requisition",
        raw_file_path="/tmp/receipt.pdf",
    )
    claim = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        invoice_date=date(2026, 4, 2),
        total=Decimal("900"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="expense_against_advance",
        raw_file_path="/tmp/claim.pdf",
    )
    db_session.add_all([advance_inv, claim])
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=advance_inv.id,
            date=date(2026, 4, 1),
            account_code=code,
            account_name="Marcus Webb",
            debit=Decimal("500"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    with pytest.raises(ValueError, match="exceeds available advance"):
        await assert_team_expense_approvable(db_session, claim)


class _Employee:
    id = "em-marcus"
    name = "Marcus Webb"


def test_against_advance_warns_when_claim_exceeds_balance() -> None:
    result = vr_te07_advance_balance(
        _Employee(),  # type: ignore[arg-type]
        900.0,
        team_expense_kind="expense_against_advance",
        advance_balance=600.0,
    )
    assert result.passed is False
    assert "exceeds available advance" in result.message


def test_against_advance_treats_none_balance_as_zero() -> None:
    result = vr_te07_advance_balance(
        _Employee(),  # type: ignore[arg-type]
        10.0,
        team_expense_kind="expense_against_advance",
        advance_balance=None,
    )
    assert result.passed is False
    assert "available advance 0.00" in result.message


def test_against_advance_passes_within_balance() -> None:
    result = vr_te07_advance_balance(
        _Employee(),  # type: ignore[arg-type]
        500.0,
        team_expense_kind="expense_against_advance",
        advance_balance=600.0,
    )
    assert result.passed is True


def test_balance_rule_skipped_for_other_kinds() -> None:
    for kind in (None, "expense_claim", "advance_requisition"):
        result = vr_te07_advance_balance(
            _Employee(),  # type: ignore[arg-type]
            9000.0,
            team_expense_kind=kind,
            advance_balance=0.0,
        )
        assert result.passed is True
