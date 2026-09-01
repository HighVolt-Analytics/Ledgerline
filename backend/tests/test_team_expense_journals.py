"""Team Expenses journal templates for advance requisition and expense claim."""

from datetime import date
from decimal import Decimal

import pytest

from app.tenant_ids import TESTING_TENANT_UUID
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType
from app.schemas.rule_book_config import (
    ChartOfAccountEntry,
    PostingDefaults,
    RuleBookConfigPayload,
    SubLedgerEntry,
    TeamExpensePostingDefaults,
    normalize_team_expense_kind,
)
from app.services.master_data.party_coa_subledger_service import (
    party_sub_ledger_code,
    resolve_party_child_mapping,
)
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.rule_book.account_mapper import AccountMapping
from app.services.rule_book.rule_book_mapper import ROUTE_TEAM

EMPLOYEE_SLUG = "em-marcus"


def _config() -> RuleBookConfigPayload:
    employee_child = SubLedgerEntry(
        code=party_sub_ledger_code(EMPLOYEE_SLUG),
        name="Marcus Webb",
        origin="party",
    )
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        team_expense_posting=TeamExpensePostingDefaults(
            default_advance_parent_ledger="Staff Advance",
            settlement_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(
                code="1300",
                name="Staff Advance",
                type="Asset",
                sub_ledgers=[employee_child],
            ),
            ChartOfAccountEntry(code="1400", name="Tax Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
            ChartOfAccountEntry(code="6100", name="Travel Expense", type="Expense"),
            ChartOfAccountEntry(code="9999", name="Suspense Account", type="Liability"),
        ],
    )


def _employee_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    mapping = resolve_party_child_mapping(
        config,
        parent_ledger_name="Staff Advance",
        slug=EMPLOYEE_SLUG,
    )
    assert mapping is not None
    return mapping


def _invoice(kind: str | None) -> Invoice:
    return Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 4, 2),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_TEAM,
        team_expense_kind=kind,
    )


def test_advance_requisition_debits_employee_child_and_credits_settlement() -> None:
    config = _config()
    lines = generate_entries(
        _invoice("advance_requisition"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
    )

    assert is_balanced(lines)
    assert len(lines) == 2
    debit, credit = lines
    assert debit.entry_type == EntryType.DEBIT
    assert debit.account_name == "Marcus Webb"
    assert debit.debit == Decimal("1100")
    assert credit.account_name == "Bank Account"
    assert credit.credit == Decimal("1100")


def test_expense_claim_credits_settlement_when_no_advance() -> None:
    config = _config()
    lines = generate_entries(
        _invoice("expense_claim"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("0"),
    )

    assert is_balanced(lines)
    credits = [ln for ln in lines if ln.credit > 0]
    assert len(credits) == 1
    assert credits[0].account_name == "Bank Account"
    assert all(ln.account_name != "Accounts Payable" for ln in lines)


def test_expense_claim_partially_nets_available_advance() -> None:
    """Claim $1100 with $500 advance → Cr advance 500 + Cr bank 600."""
    config = _config()
    lines = generate_entries(
        _invoice("expense_claim"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("500"),
    )

    assert is_balanced(lines)
    credits = {ln.account_name: ln.credit for ln in lines if ln.credit > 0}
    assert credits["Marcus Webb"] == Decimal("500")
    assert credits["Bank Account"] == Decimal("600")


def test_expense_claim_fully_nets_when_advance_covers_total() -> None:
    config = _config()
    lines = generate_entries(
        _invoice("expense_claim"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("2000"),
    )
    assert is_balanced(lines)
    credits = [ln for ln in lines if ln.credit > 0]
    assert len(credits) == 1
    assert credits[0].account_name == "Marcus Webb"
    assert credits[0].credit == Decimal("1100")


def test_legacy_against_advance_journals_as_expense_claim() -> None:
    """Stored expense_against_advance normalizes to claim (same netting rules)."""
    config = _config()
    lines = generate_entries(
        _invoice("expense_against_advance"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("0"),
    )
    claim_lines = generate_entries(
        _invoice("expense_claim"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("0"),
    )
    assert [(ln.account_name, ln.debit, ln.credit) for ln in lines] == [
        (ln.account_name, ln.debit, ln.credit) for ln in claim_lines
    ]


def test_missing_kind_defaults_to_expense_claim() -> None:
    config = _config()
    lines = generate_entries(
        _invoice(None),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("0"),
    )
    claim_lines = generate_entries(
        _invoice("expense_claim"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("0"),
    )

    assert [(ln.account_name, ln.debit, ln.credit) for ln in lines] == [
        (ln.account_name, ln.debit, ln.credit) for ln in claim_lines
    ]


def test_direct_payment_credits_settlement_without_advance_netting() -> None:
    config = _config()
    lines = generate_entries(
        _invoice("direct_payment"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
        advance_available=Decimal("500"),
    )

    assert is_balanced(lines)
    credits = [ln for ln in lines if ln.credit > 0]
    assert len(credits) == 1
    assert credits[0].account_name == "Bank Account"
    assert credits[0].credit == Decimal("1100")
    assert all(ln.account_name != "Marcus Webb" for ln in lines if ln.credit > 0)


def test_direct_payment_skips_staff_advance_control_gate() -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = ""
    unresolved = get_unresolved_control_accounts(
        invoice=_invoice("direct_payment"),
        config=config,
    )
    assert "staff_advance_account" not in unresolved


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "expense_claim"),
        ("", "expense_claim"),
        ("nonsense", "expense_claim"),
        ("Advance_Requisition", "advance_requisition"),
        ("expense_against_advance", "expense_claim"),
        ("direct_payment", "direct_payment"),
    ],
)
def test_normalize_team_expense_kind(value: str | None, expected: str) -> None:
    assert normalize_team_expense_kind(value) == expected


def test_advance_requisition_posts_gross_without_tax_line() -> None:
    config = _config()
    lines = generate_entries(
        _invoice("advance_requisition"),
        AccountMapping("6100", "Travel Expense"),
        config=config,
        control_mapping=_employee_mapping(config),
    )
    assert all(ln.account_name != "Tax Paid" for ln in lines)


def test_control_account_gate_ignores_payable_for_team_expenses() -> None:
    config = _config()
    config.posting_defaults.payable_account = "Nonexistent Payable"
    unresolved = get_unresolved_control_accounts(
        invoice=_invoice("expense_claim"),
        config=config,
    )
    assert unresolved == []


def test_control_account_gate_flags_missing_staff_advance() -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = "Missing Advance"
    unresolved = get_unresolved_control_accounts(
        invoice=_invoice("advance_requisition"),
        config=config,
    )
    assert unresolved == ["staff_advance_account"]


def test_control_account_gate_flags_empty_staff_advance() -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = ""
    unresolved = get_unresolved_control_accounts(
        invoice=_invoice("advance_requisition"),
        config=config,
    )
    assert unresolved == ["staff_advance_account"]


def test_control_account_gate_accepts_mapped_employee_advance_ledger() -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = ""
    inv = _invoice("advance_requisition")
    inv.account_code = "EM-NEW-EMPLOYEE-FAD7"
    inv.account_name = "vishnu"
    unresolved = get_unresolved_control_accounts(invoice=inv, config=config)
    assert "staff_advance_account" not in unresolved


def test_advance_requisition_journals_debit_mapped_employee_when_parent_missing() -> None:
    config = _config()
    config.team_expense_posting.default_advance_parent_ledger = ""
    inv = _invoice("advance_requisition")
    inv.account_code = "EM-NEW-EMPLOYEE-FAD7"
    inv.account_name = "vishnu"
    lines = generate_entries(
        inv,
        AccountMapping("EM-NEW-EMPLOYEE-FAD7", "vishnu"),
        config=config,
        control_mapping=AccountMapping("9999", "Suspense Account"),
    )
    assert is_balanced(lines)
    debit = next(ln for ln in lines if ln.debit > 0)
    assert debit.account_code == "EM-NEW-EMPLOYEE-FAD7"
    assert debit.account_name == "vishnu"
    assert get_unresolved_control_accounts(invoice=inv, config=config) == []


def test_team_expense_posting_defaults_are_empty_until_configured() -> None:
    posting = PostingDefaults(bank_account="Operating Bank")
    seeded = TeamExpensePostingDefaults.for_posting_defaults(posting)
    assert seeded.default_advance_parent_ledger == ""
    assert seeded.settlement_account == "Operating Bank"
    bare = TeamExpensePostingDefaults()
    assert bare.default_advance_parent_ledger == ""
    assert bare.settlement_account == ""
