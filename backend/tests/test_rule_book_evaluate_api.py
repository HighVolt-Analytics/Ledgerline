"""Rule book evaluate API."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.schemas.rule_book_config import validate_rule_book_config_payload


@pytest.mark.asyncio
async def test_evaluate_rule_book_sample(client: AsyncClient) -> None:
    res = await client.post("/api/rule-book/evaluate", json={})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["source"] == "invoices"
    assert data["rows"] == []


@pytest.mark.asyncio
async def test_evaluate_rule_book_draft_config(client: AsyncClient) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    saved = json.loads(fixture.read_text(encoding="utf-8"))
    config = validate_rule_book_config_payload(saved)
    payload = config.model_dump()
    payload["vendor_detection_config"]["threshold"] = 99

    res = await client.post("/api/rule-book/evaluate", json={"config": payload})
    assert res.status_code == 200
    rows = res.json()["data"]["rows"]
    assert all(not row["auto_coded"] for row in rows if row["category_rule"])
