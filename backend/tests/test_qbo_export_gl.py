from decimal import Decimal
from types import SimpleNamespace

from app.integrations.qbo.export_gl import split_qbo_gl_postings


def _acct(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        qbo_account_id=kwargs["qbo_account_id"],
        name=kwargs["name"],
        acct_num=kwargs.get("acct_num"),
        fully_qualified_name=kwargs.get("fully_qualified_name"),
        parent_ref=kwargs.get("parent_ref"),
        sub_account=kwargs.get("sub_account", False),
        active=True,
    )


def test_split_allotted_subs_and_unallotted_parent_remainder() -> None:
    parent = _acct(qbo_account_id="1", name="Travel")
    hotel = _acct(
        qbo_account_id="11",
        name="Hotel",
        parent_ref="1",
        sub_account=True,
        fully_qualified_name="Travel:Hotel",
    )
    meals = _acct(
        qbo_account_id="12",
        name="Meals",
        parent_ref="1",
        sub_account=True,
        fully_qualified_name="Travel:Meals",
    )
    accounts = [parent, hotel, meals]
    lines = split_qbo_gl_postings(
        parent=parent,
        accounts=accounts,
        line_items=[
            SimpleNamespace(amount=Decimal("30"), sub_ledger="Hotel"),
            SimpleNamespace(amount=Decimal("20"), sub_ledger="Meals"),
            SimpleNamespace(amount=Decimal("50"), sub_ledger=None),
        ],
        header_amount=Decimal("100"),
    )
    by_kind = {(row["kind"], row["qbo_account_id"]): row["amount"] for row in lines}
    assert by_kind[("sub", "11")] == "30.00"
    assert by_kind[("sub", "12")] == "20.00"
    assert by_kind[("parent", "1")] == "50.00"
    assert sum(Decimal(row["amount"]) for row in lines) == Decimal("100.00")


def test_split_unmatched_sub_ledger_goes_to_parent() -> None:
    parent = _acct(qbo_account_id="1", name="Travel")
    hotel = _acct(qbo_account_id="11", name="Hotel", parent_ref="1", sub_account=True)
    lines = split_qbo_gl_postings(
        parent=parent,
        accounts=[parent, hotel],
        line_items=[
            SimpleNamespace(amount=Decimal("30"), sub_ledger="Hotel"),
            SimpleNamespace(amount=Decimal("70"), sub_ledger="Unknown department"),
        ],
        header_amount=Decimal("100"),
    )
    assert lines[0]["qbo_account_id"] == "11"
    assert lines[1]["kind"] == "parent"
    assert lines[1]["amount"] == "70.00"


def test_split_header_only_posts_parent() -> None:
    parent = _acct(qbo_account_id="1", name="Travel")
    lines = split_qbo_gl_postings(
        parent=parent,
        accounts=[parent],
        line_items=[],
        header_amount=Decimal("100"),
    )
    assert lines == [
        {
            "qbo_account_id": "1",
            "name": "Travel",
            "amount": "100.00",
            "kind": "parent",
        }
    ]
