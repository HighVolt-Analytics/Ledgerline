"""Org AI brief API — tenant-scoped persistence via rule book config + RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book_config_io import load_rule_book_config_dict
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_org_ai_brief_round_trip(client: AsyncClient, db_session: AsyncSession) -> None:
    payload = {
        "legal_name": "High Volt Analytics Pty Ltd",
        "abn": "12345678901",
        "aliases": ["High Volt", "HVA"],
        "default_perspective": "buyer",
        "intake_summary": "Supplier tax invoices and GRNs.",
        "classification_hints": "Sysco is a food vendor.",
    }

    patch_res = await client.patch("/api/tenants/current/org-ai-brief", json=payload)
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()["data"]
    assert patched["legal_name"] == payload["legal_name"]
    assert patched["intake_summary"] == payload["intake_summary"]
    assert patched["aliases"] == payload["aliases"]

    get_res = await client.get("/api/tenants/current/org-ai-brief")
    assert get_res.status_code == 200, get_res.text
    loaded = get_res.json()["data"]
    assert loaded == patched

    stored = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    org = stored.get("org_context") or {}
    assert org.get("legal_name") == payload["legal_name"]
    assert org.get("classification_hints") == payload["classification_hints"]
