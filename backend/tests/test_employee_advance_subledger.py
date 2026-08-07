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
    assert employee.advance_parent_ledger == "Staff Advance"
    config = await _reload(db_session)
    assert (
        resolve_party_child_mapping(
            config, parent_ledger_name="Staff Advance", slug="em-lee"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_creating_employee_uses_custom_coa_team_default(
    db_session: AsyncSession,
) -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = "Director Advance"
    await save_rule_book_config(db_session, config, TESTING_TENANT_UUID)

    employee = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(master_id="em-custom", name="Custom Default"),
    )

    assert employee.advance_parent_ledger == "Director Advance"
    assert employee.advance_sub_ledger == "Custom Default"
    reloaded = await _reload(db_session)
    assert (
        resolve_party_child_mapping(
            reloaded, parent_ledger_name="Director Advance", slug="em-custom"
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
async def test_pending_open_claims_reserve_advance_float(
    db_session: AsyncSession,
) -> None:
    """Open expense claims reserve Staff Advance until posted (partial netting)."""
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
    open_claim = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        invoice_date=date(2026, 4, 2),
        total=Decimal("400"),
        route_target=ROUTE_TEAM,
        email_sender="marcus@example.com",
        team_expense_kind="expense_claim",
    )
    db_session.add_all([advance_inv, open_claim])
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
        exclude_invoice_id=None,
    )
    assert pending == Decimal("400")

    available, ledger, reserved = await employee_available_advance(
        db_session,
        TESTING_TENANT_UUID,
        config,
        employee,
        exclude_invoice_id=open_claim.id,
    )
    assert ledger == Decimal("1000")
    assert reserved == Decimal("0")
    assert available == Decimal("1000")

    available_with_pending, _, reserved_with = await employee_available_advance(
        db_session,
        TESTING_TENANT_UUID,
        config,
        employee,
        exclude_invoice_id=None,
    )
    assert reserved_with == Decimal("400")
    assert available_with_pending == Decimal("600")


@pytest.mark.asyncio
async def test_approve_allows_claim_without_advance_balance_gate(
    db_session: AsyncSession,
) -> None:
    """VR-TE07 retired — claim approval is not blocked by outstanding advance float."""
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
        team_expense_kind="expense_claim",
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

    await assert_team_expense_approvable(db_session, claim)


class _Employee:
    id = "em-marcus"
    name = "Marcus Webb"


def test_vr_te07_retired_for_all_kinds() -> None:
    for kind in (
        None,
        "expense_claim",
        "advance_requisition",
        "expense_against_advance",
    ):
        result = vr_te07_advance_balance(
            _Employee(),  # type: ignore[arg-type]
            9000.0,
            team_expense_kind=kind,
            advance_balance=0.0,
        )
        assert result.passed is True
        assert result.skipped is True
        assert "retired" in result.message.lower()
