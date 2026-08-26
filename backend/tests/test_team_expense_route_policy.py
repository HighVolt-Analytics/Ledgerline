"""Team Expenses route policy: primary DT picker and title-match preservation."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import EmployeeMaster
from app.services.purchase.team_expense_route_policy import (
    apply_employee_channel_team_expenses_route,
    primary_team_expenses_document_type,
    role_hints_look_commercial,
    should_apply_employee_channel_te_force,
    should_force_team_expenses,
)
from app.services.rule_book.rule_book_mapper import ROUTE_TEAM
from app.tenant_ids import TESTING_TENANT_UUID


def _te_dt(
    code: str,
    *,
    title: str,
    team_expense_kind: str = "",
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=title,
        short_title=title,
        klass="Transactional",
        posting="Yes",
        route_target=ROUTE_TEAM,
        playbook_profile="employee_claim",
        team_expense_kind=team_expense_kind,
    )


class _InvoiceStub:
    def __init__(self, **kwargs: object) -> None:
        self.document_heading = kwargs.get("document_heading", "")
        self.document_type_code = kwargs.get("document_type_code", "")
        self.document_type_confidence = kwargs.get("document_type_confidence")
        self.capture_source = kwargs.get("capture_source", "email")
        self.email_sender = kwargs.get("email_sender", "")
        self.route_target = kwargs.get("route_target", "")
        self.extracted_fields = kwargs.get("extracted_fields")


def test_primary_team_expenses_document_type_returns_none_without_match() -> None:
    catalogue = [
        _te_dt("DT-04", title="Employee expense claim", team_expense_kind="expense_claim"),
        _te_dt("DT-05", title="Advance requisition", team_expense_kind="advance_requisition"),
    ]
    assert primary_team_expenses_document_type(catalogue) is None
    assert (
        primary_team_expenses_document_type(
            catalogue,
            preferred_kind="direct_payment",
        )
        is None
    )


def test_primary_team_expenses_document_type_prefers_code_then_kind() -> None:
    catalogue = [
        _te_dt("DT-04", title="Employee expense claim", team_expense_kind="expense_claim"),
        _te_dt("DT-06", title="Payment Voucher", team_expense_kind="direct_payment"),
    ]
    by_code = primary_team_expenses_document_type(catalogue, preferred_code="DT-06")
    assert by_code is not None
    assert by_code.code == "DT-06"

    by_kind = primary_team_expenses_document_type(
        catalogue,
        preferred_kind="direct_payment",
    )
    assert by_kind is not None
    assert by_kind.code == "DT-06"


def test_apply_employee_channel_preserves_title_match_dt() -> None:
    catalogue = [
        _te_dt("DT-04", title="Employee expense claim", team_expense_kind="expense_claim"),
        _te_dt("DT-06", title="Payment Voucher", team_expense_kind="direct_payment"),
    ]
    employee = EmployeeMaster(
        id="e1",
        name="Khushi",
        email="ka12122000@gmail.com",
        status="Active",
    )
    inv = _InvoiceStub(
        document_heading="Payment Voucher",
        document_type_code="DT-06",
        document_type_confidence=0.97,
        capture_source="email",
        email_sender="ka12122000@gmail.com",
    )
    apply_employee_channel_team_expenses_route(inv, catalogue, [employee])
    assert inv.route_target == ROUTE_TEAM
    assert inv.document_type_code == "DT-06"


def test_apply_employee_channel_fills_empty_dt() -> None:
    catalogue = [
        _te_dt("DT-04", title="Employee expense claim", team_expense_kind="expense_claim"),
    ]
    employee = EmployeeMaster(
        id="e1",
        name="Ka",
        email="ka@acme.com",
        status="Active",
    )
    inv = _InvoiceStub(
        document_heading="Family Floral Gift Shop",
        document_type_code="",
        capture_source="email",
        email_sender="ka@acme.com",
    )
    apply_employee_channel_team_expenses_route(inv, catalogue, [employee])
    assert inv.route_target == ROUTE_TEAM
    assert inv.document_type_code == "DT-04"


def test_role_hints_look_commercial_requires_po_so_or_credit_note() -> None:
    assert role_hints_look_commercial({}) is False
    assert role_hints_look_commercial(None) is False
    assert role_hints_look_commercial({"has_invoice_number": "true"}) is False
    assert role_hints_look_commercial({"has_po_reference": "true"}) is True
    assert role_hints_look_commercial({"has_so_reference": "true"}) is True
    assert role_hints_look_commercial({"is_credit_note": "true"}) is True
    assert role_hints_look_commercial({"has_po_reference": "false"}) is False


def test_employee_channel_force_skips_when_hints_are_commercial() -> None:
    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = _InvoiceStub(
        capture_source="email",
        email_sender="priya@acme.com",
        document_type_code="AP-01",
        extracted_fields={"document_role_hints": {"has_po_reference": "true"}},
    )
    assert should_force_team_expenses(inv, [employee]) is True
    assert should_apply_employee_channel_te_force(inv, [employee]) is False
    apply_employee_channel_team_expenses_route(inv, [_te_dt("DT-04", title="Claim", team_expense_kind="expense_claim")], [employee])
    assert inv.route_target != ROUTE_TEAM
    assert inv.document_type_code == "AP-01"


def test_employee_channel_force_keeps_when_only_invoice_number_hint() -> None:
    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    inv = _InvoiceStub(
        capture_source="email",
        email_sender="priya@acme.com",
        document_type_code="",
        extracted_fields={"document_role_hints": {"has_invoice_number": "true"}},
    )
    assert should_apply_employee_channel_te_force(inv, [employee]) is True
    apply_employee_channel_team_expenses_route(
        inv,
        [_te_dt("DT-04", title="Claim", team_expense_kind="expense_claim")],
        [employee],
    )
    assert inv.route_target == ROUTE_TEAM
    assert inv.document_type_code == "DT-04"


def test_should_apply_honours_explicit_force_override_and_still_skips_commercial() -> None:
    employee = EmployeeMaster(
        id="e1", name="Priya", email="priya@acme.com", status="Active"
    )
    unknown = _InvoiceStub(
        capture_source="email",
        email_sender="not-an-employee@acme.com",
        extracted_fields={"document_role_hints": {"has_po_reference": "true"}},
    )
    assert should_apply_employee_channel_te_force(unknown, [employee]) is False
    assert (
        should_apply_employee_channel_te_force(
            unknown, [employee], force_team_expenses=True
        )
        is False
    )
    claimish = _InvoiceStub(
        capture_source="email",
        email_sender="not-an-employee@acme.com",
        extracted_fields={"document_role_hints": {"has_invoice_number": "true"}},
    )
    assert (
        should_apply_employee_channel_te_force(
            claimish, [employee], force_team_expenses=True
        )
        is True
    )
