"""Rule book document type recognition test API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _grn_draft() -> dict:
    return {
        "code": "DT-99",
        "title": "GRN",
        "shortTitle": "GRN",
        "klass": "Supporting",
        "posting": "No",
        "fraudRisk": "low",
        "oneLine": "Goods received",
        "routeTarget": "Vault",
        "enabled": True,
        "classifier": {
            "enabled": True,
            "priority": 100,
            "confidence": 0.85,
            "root": {
                "type": "group",
                "operator": "OR",
                "children": [
                    {
                        "type": "condition",
                        "field": "document_text",
                        "operator": "contains",
                        "value": "GRN",
                    },
                ],
            },
        },
    }


@pytest.mark.asyncio
async def test_recognition_test_api_matches(client: AsyncClient) -> None:
    res = await client.post(
        "/api/rule-book/document-types/test-recognition",
        json={
            "draft_document_type": _grn_draft(),
            "document_text": "GRN PO 12345 received qty 10",
            "document_heading": "GOODS RECEIVED",
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["matches"] is True
    assert data["match_rules_passed"] is True
    assert data["classifier_enabled"] is True


@pytest.mark.asyncio
async def test_recognition_test_api_no_match(client: AsyncClient) -> None:
    res = await client.post(
        "/api/rule-book/document-types/test-recognition",
        json={
            "draft_document_type": _grn_draft(),
            "document_text": "Monthly bank statement only",
        },
    )
    assert res.status_code == 200
    assert res.json()["data"]["matches"] is False
