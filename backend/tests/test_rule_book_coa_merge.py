"""Rule book PUT must preserve tenant COA for Post-to validation when body omits chart_of_accounts."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.tenant_ids import TESTING_TENANT_UUID

_COA_ACCOUNTS = [
    {"code": "6140", "name": "R&D Expense", "type": "Expense"},
    {"code": "6130", "name": "Marketing Expense", "type": "Expense"},
    {"code": "9999", "name": "Suspense Account", "type": "Liability"},
]


def _document_type(code: str, ledger: str, *, posting: str = "Yes") -> dict:
    return {
        "code": code,
        "title": f"Test type {code}",
        "shortTitle": f"Test {code}",
        "klass": "Transactional",
        "posting": posting,
        "oneLine": f"Test document type {code}",
        "routeTarget": "Purchase Management",
        "enabled": True,
        "postTo": {"ledger": ledger, "subLedger": ""},
        "classifier": {
            "enabled": False,
            "priority": 100,
            "confidence": 0.85,
            "root": {"type": "group", "operator": "AND", "children": []},
        },
    }


@pytest.mark.asyncio
async def test_put_rule_book_merges_stored_coa_for_post_to_validation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    patch_res = await client.patch(
        "/api/tenants/current/chart-of-accounts",
        json={"accounts": _COA_ACCOUNTS},
    )
    assert patch_res.status_code == 200, patch_res.text

    get_res = await client.get("/api/rule-book/config")
    assert get_res.status_code == 200, get_res.text
    body = get_res.json()["data"]
    body.pop("chart_of_accounts", None)
    body.pop("vendor_masters", None)
    body.pop("employee_masters", None)
    body["document_types"] = [
        _document_type("DT-06", "R&D Expense"),
        _document_type("DT-09", "Marketing Expense"),
    ]

    put_res = await client.put("/api/rule-book/config", json=body)
    assert put_res.status_code == 200, put_res.text

    stored = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    stored_names = {row["name"] for row in stored.get("chart_of_accounts", [])}
    assert "R&D Expense" in stored_names
    assert "Marketing Expense" in stored_names

    saved_types = {
        row["code"].strip().upper(): row
        for row in put_res.json()["data"].get("document_types", [])
        if isinstance(row, dict) and row.get("code")
    }
    assert saved_types["DT-06"]["post_to"]["ledger"] == "R&D Expense"
    assert saved_types["DT-09"]["post_to"]["ledger"] == "Marketing Expense"
