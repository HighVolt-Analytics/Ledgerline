"""Tests for line-item sub-ledger GL mapping."""

from decimal import Decimal
import uuid

from app.models.line_item import LineItem
from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
from app.schemas.rule_book_config import ChartOfAccountEntry, RuleBookConfigPayload
from app.services.classification.line_gl_mapping_service import (
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
    from types import SimpleNamespace

    config = _config_with_sub_ledgers()
    invoice = SimpleNamespace(vendor="Amazon Web Services", document_type_code="DT-01")
    sub, source, _reason = _fallback_sub_ledger(
        invoice, config, parent_ledger="Cloud Hosting Expense"
    )
    assert sub == "AWS Production"
    assert source == "doc_type_default"


def test_keyword_sub_ledger_hint() -> None:
    catalogue = build_line_sub_ledger_catalogue(
        "Cloud Hosting Expense",
        _config_with_sub_ledgers().chart_of_accounts,
    )
    assert _keyword_sub_ledger_hint("AWS monthly hosting", catalogue) == "AWS Production"
