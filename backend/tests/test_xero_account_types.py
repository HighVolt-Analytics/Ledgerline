from app.integrations.xero.account_types import (
    default_subtype,
    ledger_type_for_xero,
    normalize_subtype,
)


def test_xero_subtypes_map_to_ledger_classes() -> None:
    assert ledger_type_for_xero(account_type="OTHERINCOME") == "Revenue"
    assert ledger_type_for_xero(account_type="CURRENT") == "Asset"
    assert ledger_type_for_xero(account_type="CURRLIAB") == "Liability"
    assert ledger_type_for_xero(account_type="EXPENSE") == "Expense"
    assert ledger_type_for_xero(account_type=None, account_class="ASSET") == "Asset"


def test_normalize_subtype_resets_when_type_changes() -> None:
    assert default_subtype("Asset") == "CURRENT"
    assert normalize_subtype("Expense", "CURRENT") == "EXPENSE"
    assert normalize_subtype("Revenue", "OTHERINCOME") == "OTHERINCOME"
