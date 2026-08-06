"""Tests for line-item sub-ledger GL mapping."""

from decimal import Decimal
from types import SimpleNamespace
import uuid

from app.models.line_item import LineItem
from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
from app.schemas.rule_book_config import ChartOfAccountEntry, RuleBookConfigPayload
from app.services.classification.line_gl_mapping_service import (
    _accept_llm_sub_ledger,
    _fallback_sub_ledger,
    _keyword_sub_ledger_hint,
)
from app.services.extraction.llm_coa_catalogue import (
    build_line_sub_ledger_catalogue,
    parent_ledger_has_sub_ledger_catalogue,
)
from app.services.invoice.line_item_gl_service import (
    build_line_item_response,
    effective_line_ledger,
    line_gl_mapping_applicable,
    line_sub_ledger_review_required,
    missing_line_sub_ledger_indexes,
    resolve_effective_ledger_mapping,
)


def _config_with_sub_ledgers() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(
                code="6110",
                name="Cloud Hosting Expense",
                type="Expense",
                sub_ledgers=[
                    {"code": "01", "name": "AWS Production"},
                    {"code": "02", "name": "Azure Staging"},
                ],
            ),
        ],
        document_types=[
            DocumentTypeDefinition(
                code="DT-01",
                title="Invoice",
                short_title="Invoice",
                klass="Transactional",
                posting="Yes",
                recognition_mode="signals",
                recognition_signals=["heading_invoice"],
                llm_prompt="",
                route_target="Purchase Management",
                post_to=DocumentTypePostTo(ledger="Cloud Hosting Expense", sub_ledger="AWS Production"),
            ),
            DocumentTypeDefinition(
                code="DT-08",
                title="Employee expense claim / reimbursement",
                short_title="Expense claim",
                klass="Transactional",
                posting="Yes",
                recognition_mode="signals",
                recognition_signals=[],
                llm_prompt="",
                route_target="Team Expenses",
                playbook_profile="employee_claim",
                post_to=DocumentTypePostTo(ledger="Cloud Hosting Expense", sub_ledger=""),
            ),
        ],
    )


def test_build_line_sub_ledger_catalogue() -> None:
    config = _config_with_sub_ledgers()
    rows = build_line_sub_ledger_catalogue("Cloud Hosting Expense", config.chart_of_accounts)
    assert len(rows) == 2
    assert rows[0]["name"] == "AWS Production"


def test_parent_without_catalogue() -> None:
    config = RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense"),
        ]
    )
    assert not parent_ledger_has_sub_ledger_catalogue(
        "Operating Expenses", config.chart_of_accounts
    )


def test_effective_line_ledger_prefers_sub_ledger() -> None:
    assert effective_line_ledger(sub_ledger="AWS Production", parent_ledger="Cloud Hosting Expense") == "AWS Production"
    assert effective_line_ledger(sub_ledger="", parent_ledger="Operating Expenses") == "Operating Expenses"


def test_build_line_item_response() -> None:
    line = LineItem(
        id=1,
        tenant_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440001"),
        invoice_id=10,
        description="Hosting",
        sub_ledger="AWS Production",
        gl_mapping_source="llm",
        gl_mapping_confidence=Decimal("0.9100"),
        gl_mapping_reason="SaaS line",
    )
    response = build_line_item_response(line, parent_ledger="Cloud Hosting Expense")
    assert response.parent_ledger == "Cloud Hosting Expense"
    assert response.effective_ledger == "AWS Production"
    assert response.gl_mapping_source == "llm"


def test_fallback_sub_ledger_uses_doc_type_default() -> None:
    config = _config_with_sub_ledgers()
    invoice = SimpleNamespace(vendor="Amazon Web Services", document_type_code="DT-01")
    sub, source, _reason = _fallback_sub_ledger(
        invoice, config, parent_ledger="Cloud Hosting Expense"
    )
    assert sub == "AWS Production"
    assert source == "doc_type_default"


def test_fallback_keeps_main_gl_when_parent_has_no_subs() -> None:
    config = RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense"),
        ],
        document_types=[
            DocumentTypeDefinition(
                code="DT-01",
                title="Invoice",
                short_title="Invoice",
                klass="Transactional",
                posting="Yes",
                recognition_mode="signals",
                recognition_signals=[],
                llm_prompt="",
                route_target="Purchase Management",
                post_to=DocumentTypePostTo(ledger="Operating Expenses", sub_ledger=""),
            ),
        ],
    )
    invoice = SimpleNamespace(vendor="Acme", document_type_code="DT-01")
    sub, source, reason = _fallback_sub_ledger(
        invoice, config, parent_ledger="Operating Expenses"
    )
    assert sub == ""
    assert source == "main_gl"
    assert "main GL" in reason



def test_keyword_sub_ledger_hint() -> None:
    catalogue = build_line_sub_ledger_catalogue(
        "Cloud Hosting Expense",
        _config_with_sub_ledgers().chart_of_accounts,
    )
    assert _keyword_sub_ledger_hint("AWS monthly hosting", catalogue) == "AWS Production"


def test_line_gl_mapping_applies_to_team_expense_claims() -> None:
    config = _config_with_sub_ledgers()
    invoice = SimpleNamespace(
        document_type_code="DT-08",
        route_target="Team Expenses",
        account_name="Cloud Hosting Expense",
        gl_posting_applicable=True,
        team_expense_kind="expense_claim",
    )
    assert line_gl_mapping_applicable(invoice, config) is True


def test_line_gl_mapping_skips_team_expense_advances() -> None:
    config = _config_with_sub_ledgers()
    invoice = SimpleNamespace(
        document_type_code="DT-08",
        route_target="Team Expenses",
        account_name="Cloud Hosting Expense",
        gl_posting_applicable=True,
        team_expense_kind="advance_requisition",
    )
    assert line_gl_mapping_applicable(invoice, config) is False


def test_stamp_team_expense_header_sub_ledger_from_document() -> None:
    from app.services.classification.line_gl_mapping_service import (
        stamp_team_expense_header_sub_ledger,
    )

    config = _config_with_sub_ledgers()
    invoice = SimpleNamespace(
        id=1,
        document_type_code="DT-08",
        route_target="Team Expenses",
        account_name="Cloud Hosting Expense",
        account_code="6110",
        team_expense_kind="expense_claim",
        line_items=[],
        document_text="AWS Production hosting for March",
        document_heading="",
        vendor="Amazon",
    )
    assert (
        stamp_team_expense_header_sub_ledger(
            invoice,
            config,
            document_sub_ledger="AWS Production",
            document_confidence=0.95,
            document_reasoning="Hosting vendor",
        )
        is True
    )
    assert invoice.account_name == "AWS Production"
    assert invoice.account_code == "6110-01"


def test_line_sub_ledger_review_required_when_catalogue_and_blank() -> None:
    config = _config_with_sub_ledgers()
    line = SimpleNamespace(sub_ledger=None)
    invoice = SimpleNamespace(
        document_type_code="DT-01",
        route_target="Purchase Management",
        account_name="Cloud Hosting Expense",
        gl_posting_applicable=True,
        line_items=[line],
    )
    assert line_sub_ledger_review_required(invoice, config) is True
    assert missing_line_sub_ledger_indexes(invoice) == [0]


def test_line_sub_ledger_review_not_required_without_catalogue() -> None:
    config = RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense"),
        ],
        document_types=[
            DocumentTypeDefinition(
                code="DT-01",
                title="Invoice",
                short_title="Invoice",
                klass="Transactional",
                posting="Yes",
                recognition_mode="signals",
                recognition_signals=[],
                llm_prompt="",
                route_target="Purchase Management",
                post_to=DocumentTypePostTo(ledger="Operating Expenses", sub_ledger=""),
            ),
        ],
    )
    invoice = SimpleNamespace(
        document_type_code="DT-01",
        route_target="Purchase Management",
        account_name="Operating Expenses",
        gl_posting_applicable=True,
        line_items=[SimpleNamespace(sub_ledger=None)],
    )
    assert line_sub_ledger_review_required(invoice, config) is False


def test_resolve_effective_ledger_mapping_nested_sub() -> None:
    config = _config_with_sub_ledgers()
    mapping = resolve_effective_ledger_mapping(
        parent_ledger="Cloud Hosting Expense",
        effective_ledger="AWS Production",
        config=config,
    )
    assert mapping.account_code == "6110-01"
    assert mapping.account_name == "AWS Production"


def test_accept_llm_sub_ledger_requires_min_confidence() -> None:
    config = _config_with_sub_ledgers()
    assert (
        _accept_llm_sub_ledger(
            "AWS Production",
            0.9,
            parent_ledger="Cloud Hosting Expense",
            accounts=config.chart_of_accounts,
            min_confidence=0.85,
        )
        is True
    )
    assert (
        _accept_llm_sub_ledger(
            "AWS Production",
            0.5,
            parent_ledger="Cloud Hosting Expense",
            accounts=config.chart_of_accounts,
            min_confidence=0.85,
        )
        is False
    )
    assert (
        _accept_llm_sub_ledger(
            "AWS Production",
            None,
            parent_ledger="Cloud Hosting Expense",
            accounts=config.chart_of_accounts,
            min_confidence=0.85,
        )
        is False
    )
