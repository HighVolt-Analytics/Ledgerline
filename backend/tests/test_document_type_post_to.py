"""Document-type Post to GL defaults and validation."""

from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
from app.schemas.rule_book_config import ChartOfAccountEntry
from app.services.classification.document_type_gl_defaults import (
    default_post_to_ledger,
    resolve_coa_account_name,
    suggested_ledger_for_playbook_profile,
)
from app.services.classification.document_type_post_to_service import (
    document_type_requires_post_to,
    has_valid_document_type_post_to,
)


def test_suggested_ledger_by_playbook_profile() -> None:
    assert suggested_ledger_for_playbook_profile("po_goods") == "Raw Materials"
    assert suggested_ledger_for_playbook_profile("ar_goods") == "Operating Revenue"
    assert suggested_ledger_for_playbook_profile("supporting") == ""


def test_resolve_coa_account_name_fuzzy() -> None:
    accounts = [
        ChartOfAccountEntry(code="5100", name="Raw Materials", type="Expense"),
        ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense"),
    ]
    assert resolve_coa_account_name("raw materials", accounts) == "Raw Materials"
    assert resolve_coa_account_name("Unknown", accounts) == ""


def test_default_post_to_ledger_from_profile() -> None:
    accounts = [
        ChartOfAccountEntry(code="5100", name="Raw Materials", type="Expense"),
    ]
    assert default_post_to_ledger("po_goods", accounts) == "Raw Materials"
    assert default_post_to_ledger("supporting", accounts) == ""


def test_default_post_to_ledger_sparse_revenue_coa() -> None:
    accounts = [ChartOfAccountEntry(code="1", name="sales", type="Revenue")]
    assert default_post_to_ledger("ar_goods", accounts) == "sales"
    assert default_post_to_ledger("", accounts, route_target="Sales Management") == "sales"


def test_has_valid_document_type_post_to() -> None:
    accounts = [ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense")]
    transactional = DocumentTypeDefinition(
        code="DT-01",
        title="Invoice",
        short_title="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        route_target="Purchase Management",
        post_to=DocumentTypePostTo(ledger="Operating Expenses"),
    )
    assert document_type_requires_post_to(transactional)
    assert has_valid_document_type_post_to(transactional, accounts)

    missing = transactional.model_copy(update={"post_to": DocumentTypePostTo(ledger="")})
    assert not has_valid_document_type_post_to(missing, accounts)

    optional = transactional.model_copy(update={"posting": "No", "post_to": DocumentTypePostTo(ledger="")})
    assert not document_type_requires_post_to(optional)
    assert has_valid_document_type_post_to(optional, accounts)


def test_validate_rule_book_config_for_save_rejects_missing_post_to() -> None:
    import pytest

    from app.schemas.rule_book_config import RuleBookPostToValidationError, validate_rule_book_config_for_save

    with pytest.raises(RuleBookPostToValidationError, match="DT-BAD"):
        validate_rule_book_config_for_save(
            {
                "schema_version": 1,
                "chart_of_accounts": [
                    {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
                ],
                "document_types": [
                    {
                        "code": "DT-BAD",
                        "title": "Missing GL",
                        "shortTitle": "Missing GL",
                        "klass": "Transactional",
                        "posting": "Yes",
                        "recognition_mode": "signals", "recognition_signals": ["heading_invoice"], "llm_prompt": "Needs Post to",
                        "routeTarget": "Purchase Management",
                        "enabled": True,
                        "postTo": {"ledger": ""},
                    }
                ],
            }
        )
