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


def test_default_post_to_ledger_po_goods_falls_back_to_expense_coa() -> None:
    accounts = [
        ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense"),
        ChartOfAccountEntry(code="1000", name="Bank", type="Asset"),
    ]
    assert default_post_to_ledger("po_goods", accounts) == "Operating Expenses"


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


def test_advance_requisition_does_not_require_expense_post_to() -> None:
    accounts = [ChartOfAccountEntry(code="6100", name="Operating Expenses", type="Expense")]
    advance_dt = DocumentTypeDefinition(
        code="DT-09",
        title="Employee advance request",
        short_title="Advance",
        klass="Transactional",
        posting="Yes",
        recognition_mode="prompt",
        recognition_signals=[],
        llm_prompt="",
        route_target="Team Expenses",
        team_expense_kind="advance_requisition",
        post_to=DocumentTypePostTo(ledger=""),
    )
    assert not document_type_requires_post_to(advance_dt)
    assert has_valid_document_type_post_to(advance_dt, accounts)


def test_validate_rule_book_config_for_save_rejects_missing_post_to() -> None:
    import pytest

    from app.schemas.rule_book_config import RuleBookPostToValidationError, validate_rule_book_config_for_save

    with pytest.raises(RuleBookPostToValidationError, match="DT-BAD"):
        validate_rule_book_config_for_save(
            {
                "schema_version": 1,
                "chart_of_accounts": [],
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


def test_validate_rule_book_allows_control_account_post_to() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_for_save
    from app.services.classification.document_type_post_to_service import (
        has_valid_document_type_post_to,
        is_control_post_to_ledger,
    )

    assert is_control_post_to_ledger("Accounts Payable") is True

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "2000", "name": "Accounts Payable", "type": "Liability"},
                {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
            ],
            "posting_defaults": {"payable_account": "Accounts Payable"},
            "document_types": [
                {
                    "code": "DT-AP",
                    "title": "PO goods",
                    "shortTitle": "PO goods",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "po_goods",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": "Accounts Payable"},
                }
            ],
        }
    )
    assert payload.document_types[0].post_to.ledger == "Accounts Payable"
    assert has_valid_document_type_post_to(
        payload.document_types[0],
        payload.chart_of_accounts,
        posting_defaults=payload.posting_defaults,
    )


def test_validate_rule_book_rejects_commercial_with_bundle_role() -> None:
    import pytest

    from app.schemas.rule_book_config import (
        RuleBookDocumentTypeInvariantError,
        validate_rule_book_config_for_save,
    )

    with pytest.raises(RuleBookDocumentTypeInvariantError, match="bundle role"):
        validate_rule_book_config_for_save(
            {
                "schema_version": 1,
                "chart_of_accounts": [
                    {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
                ],
                "document_types": [
                    {
                        "code": "DT-MIX",
                        "title": "Bad mix",
                        "shortTitle": "Bad mix",
                        "klass": "Transactional",
                        "posting": "Yes",
                        "playbookProfile": "po_goods",
                        "purchaseBundleRole": "grn",
                        "recognition_mode": "signals",
                        "recognition_signals": ["heading_invoice"],
                        "llm_prompt": "",
                        "routeTarget": "Purchase Management",
                        "enabled": True,
                        "postTo": {"ledger": "Operating Expenses"},
                    }
                ],
            }
        )


def test_validate_rule_book_allows_duplicate_po_roles_as_catalogue_warning() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_for_save

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
            ],
            "document_types": [
                {
                    "code": "DT-PO-A",
                    "title": "PO A",
                    "shortTitle": "PO A",
                    "klass": "Non-transactional",
                    "posting": "No",
                    "playbookProfile": "supporting",
                    "purchaseBundleRole": "po",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_purchase_order"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": ""},
                },
                {
                    "code": "DT-PO-B",
                    "title": "PO B",
                    "shortTitle": "PO B",
                    "klass": "Non-transactional",
                    "posting": "No",
                    "playbookProfile": "supporting",
                    "purchaseBundleRole": "po",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_purchase_order"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": ""},
                },
            ],
        }
    )
    assert len(payload.document_types) == 2


def test_validate_rule_book_scrubs_ledger_on_supporting_role() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_for_save

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "4000", "name": "Sales Revenue", "type": "Revenue"},
            ],
            "document_types": [
                {
                    "code": "DT-DN",
                    "title": "Delivery note",
                    "shortTitle": "DN",
                    "klass": "Non-transactional",
                    "posting": "No",
                    "playbookProfile": "supporting",
                    "salesBundleRole": "dn",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_delivery_note"],
                    "llm_prompt": "",
                    "routeTarget": "Sales Management",
                    "enabled": True,
                    "postTo": {"ledger": "Sales Revenue"},
                }
            ],
        }
    )
    assert payload.document_types[0].post_to.ledger == ""


def test_validate_rule_book_allows_matrix_playbook_drift_as_catalogue_warning() -> None:
    from app.schemas.rule_book_config import validate_rule_book_config_for_save

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
            ],
            "document_types": [
                {
                    "code": "DT-ORG",
                    "matrixTemplateCode": "DT-01",
                    "title": "PO-based goods invoice",
                    "shortTitle": "PO goods invoice",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "direct_expense",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": "Operating Expenses"},
                }
            ],
        }
    )
    assert payload.document_types[0].playbook_profile == "direct_expense"


def test_commercial_due_date_not_forced_on_save() -> None:
    """Unstarring due_date on po_goods must survive save (no silent re-star)."""
    from app.schemas.rule_book_config import validate_rule_book_config_for_save

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "6100", "name": "Operating Expenses", "type": "Expense"},
            ],
            "document_types": [
                {
                    "code": "DT-DUE",
                    "title": "PO goods",
                    "shortTitle": "PO goods",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "po_goods",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "requiredFields": ["vendor", "total"],
                    "extractionFields": ["vendor", "total", "due_date"],
                    "postTo": {"ledger": "Operating Expenses"},
                }
            ],
        }
    )
    assert payload.document_types[0].required_fields == ["vendor", "total"]
    assert "due_date" not in payload.document_types[0].required_fields


def test_orphaned_post_to_ledger_remaps_to_coa_expense() -> None:
    """Starter 'Operating Expenses' remaps when tenant COA no longer has it."""
    from app.schemas.rule_book_config import validate_rule_book_config_for_save

    payload = validate_rule_book_config_for_save(
        {
            "schema_version": 1,
            "chart_of_accounts": [
                {"code": "6200", "name": "Marketing Expenses", "type": "Expense"},
                {"code": "1000", "name": "Bank Account", "type": "Asset"},
            ],
            "document_types": [
                {
                    "code": "DT-03",
                    "title": "Expense claim",
                    "shortTitle": "Claim",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "employee_claim",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Team Expenses",
                    "enabled": True,
                    "postTo": {"ledger": "Operating Expenses"},
                },
                {
                    "code": "DT-09",
                    "title": "Direct expense",
                    "shortTitle": "Direct",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "direct_expense",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": "Operating Expenses"},
                },
                {
                    "code": "DT-10",
                    "title": "Invoice",
                    "shortTitle": "Invoice",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "playbookProfile": "standard_transactional",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "enabled": True,
                    "postTo": {"ledger": "Operating Expenses"},
                },
            ],
        }
    )
    for defn in payload.document_types:
        assert defn.post_to.ledger == "Marketing Expenses"
