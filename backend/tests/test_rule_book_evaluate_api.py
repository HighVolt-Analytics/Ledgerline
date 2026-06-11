"""Rule book evaluate API."""

import pytest
from httpx import AsyncClient

from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.rule_book_config_io import load_rule_book_config_dict


@pytest.mark.asyncio
async def test_evaluate_rule_book_sample(client: AsyncClient) -> None:
    res = await client.post("/api/rule-book/evaluate", json={})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["source"] == "invoices"
    assert data["rows"] == []


@pytest.mark.asyncio
async def test_evaluate_rule_book_draft_config(client: AsyncClient) -> None:
    saved = load_rule_book_config_dict(1)
    config = validate_rule_book_config_payload(saved)
    payload = config.model_dump()
    payload["vendor_detection_config"]["threshold"] = 99

    res = await client.post("/api/rule-book/evaluate", json={"config": payload})
    assert res.status_code == 200
    rows = res.json()["data"]["rows"]
    assert all(not row["auto_coded"] for row in rows if row["category_rule"])
