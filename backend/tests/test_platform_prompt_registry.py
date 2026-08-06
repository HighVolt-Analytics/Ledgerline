"""Platform prompt registry (Developer Port) tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.llm_document_service import build_classify_system_prompt
from app.services.prompt_registry import (
    activate_version,
    create_version,
    ensure_seeded,
    invalidate_prompt_cache,
    list_prompt_summaries,
    list_versions,
    resolve_system_prompt,
    resolve_system_prompt_text,
    warm_prompt_cache,
)
from app.services.prompt_registry.catalog import PROMPT_CATALOG
from app.services.tenant.tenant_org_context import OrgContext
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers
from app.models.user import UserRole
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _clear_prompt_cache() -> None:
    invalidate_prompt_cache()
    yield
    invalidate_prompt_cache()


@pytest.mark.asyncio
async def test_ensure_seeded_creates_v1_active(db_session: AsyncSession) -> None:
    created = await ensure_seeded(db_session)
    assert created == len(PROMPT_CATALOG)
    created_again = await ensure_seeded(db_session)
    assert created_again == 0

    summaries = await list_prompt_summaries(db_session)
    assert len(summaries) == len(PROMPT_CATALOG)
    classify = next(s for s in summaries if s["key"] == "llm.classify.system")
    assert classify["version"] == 1
    assert classify["is_overridden"] is False
    assert "suggested_dt" in classify["body"]


@pytest.mark.asyncio
async def test_sync_upgrades_stale_vision_header_prompt(db_session: AsyncSession) -> None:
    from app.services.prompt_registry.service import sync_catalog_prompt_upgrades

    await ensure_seeded(db_session)
    stale = (
        "You extract header identity fields.\n"
        "Return JSON only with keys:\n"
        "document_heading, canonical_document_type, counterparty_name, perspective,\n"
        "invoice_no, po_reference, so_reference, other_reference, confidence, reason.\n"
        "Do not extract amounts or line items."
    )
    await create_version(
        db_session,
        "vision.header_extract.system",
        body=stale,
        notes="stale seed for test",
    )
    upgraded = await sync_catalog_prompt_upgrades(db_session)
    assert upgraded == 1
    body = resolve_system_prompt_text("vision.header_extract.system")
    assert "invoice_date" in body
    assert "total" in body
    assert "currency" in body


@pytest.mark.asyncio
async def test_sync_activates_existing_catalog_version_without_duplicate(
    db_session: AsyncSession,
) -> None:
    """Stale active + catalog body already stored → activate, do not re-insert."""
    from sqlalchemy import select

    from app.models.platform_prompt import PlatformPromptVersion
    from app.services.prompt_registry.catalog import get_prompt_definition
    from app.services.prompt_registry.service import sync_catalog_prompt_upgrades

    key = "pdf.segment.system"
    defn = get_prompt_definition(key)
    assert defn is not None
    await ensure_seeded(db_session)

    stale = "You split PDFs.\nHARD COVERAGE RULES only — missing bidirectional window."
    await create_version(db_session, key, body=stale, notes="stale")
    await create_version(db_session, key, body=defn.default_body, notes="catalog")
    # Leave active on stale middle version.
    await activate_version(db_session, key, 2)

    before = (
        await db_session.execute(
            select(PlatformPromptVersion.version).where(PlatformPromptVersion.prompt_key == key)
        )
    ).scalars().all()
    upgraded = await sync_catalog_prompt_upgrades(db_session)
    assert upgraded == 1
    after = (
        await db_session.execute(
            select(PlatformPromptVersion.version).where(PlatformPromptVersion.prompt_key == key)
        )
    ).scalars().all()
    assert sorted(after) == sorted(before)

    versions = await list_versions(db_session, key)
    assert versions is not None
    active = next(v for v in versions if v["is_active"])
    assert active["version"] == 3
    assert "CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …" in active["body"]


@pytest.mark.asyncio
async def test_resolve_uses_active_version_after_warm(db_session: AsyncSession) -> None:
    await ensure_seeded(db_session)
    await create_version(
        db_session,
        "llm.classify.system",
        body=PROMPT_CATALOG[0].default_body.replace(
            "You classify finance documents",
            "OVERRIDE classify finance documents",
        ),
        notes="test override",
    )
    await db_session.commit()
    invalidate_prompt_cache()
    await warm_prompt_cache(db_session)

    resolved = resolve_system_prompt("llm.classify.system", party_rules="- party")
    assert resolved.version == 2
    assert resolved.body.startswith("OVERRIDE classify")
    assert "- party" in resolved.body


@pytest.mark.asyncio
async def test_create_version_then_activate_previous(db_session: AsyncSession) -> None:
    await ensure_seeded(db_session)
    defn = next(p for p in PROMPT_CATALOG if p.key == "pdf.segment.system")
    await create_version(
        db_session,
        "pdf.segment.system",
        body=defn.default_body + "\n# v2 marker",
        notes="v2",
    )
    await create_version(
        db_session,
        "pdf.segment.system",
        body=defn.default_body + "\n# v3 marker",
        notes="v3",
    )
    versions = await list_versions(db_session, "pdf.segment.system")
    assert versions is not None
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert versions[0]["is_active"] is True

    await activate_version(db_session, "pdf.segment.system", 1)
    await warm_prompt_cache(db_session)
    text = resolve_system_prompt_text("pdf.segment.system")
    assert "# v2 marker" not in text
    assert "# v3 marker" not in text
    assert "ROLE — Document Splitting Agent" in text
    assert "HARD COVERAGE RULES" in text
    assert "CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …" in defn.default_body


@pytest.mark.asyncio
async def test_resolve_falls_back_to_code_without_cache() -> None:
    invalidate_prompt_cache()
    resolved = resolve_system_prompt("pdf.segment.system")
    assert resolved.version == "code"
    assert "ROLE — Document Splitting Agent" in resolved.body
    assert "You split a multi-page PDF" in resolved.body
    assert "CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …" in resolved.body
    assert "DECISION ORDER (mandatory for every page i)" in resolved.body
    assert "(1) LOOK BACK — does a NEW document start at i?" in resolved.body
    assert "(2) LOOK AHEAD — does this page OPEN / CONTINUE a multi-page single document?" in resolved.body
    assert "(3) LOOK AHEAD FOR TYPE CHANGE — when to CLOSE the current run" in resolved.body
    assert "Page 0: SKIP this step (no previous)" in resolved.body
    assert 'WHAT "ONE DOCUMENT" MEANS' in resolved.body
    assert "CLASSIFICATION HEURISTICS H1–H3" in resolved.body
    assert "PHASE 3 — GROUPING (G1–G4)" in resolved.body
    assert "FAILURE MODES (detect in reasoning; do not silently collapse)" in resolved.body
    assert "DOCUMENT TYPE TAXONOMY" in resolved.body
    assert "Prefer correct single-document boundaries" in resolved.body
    assert "BLANK / EMPTY PAGES (MUST SKIP AS DOCUMENTS)" in resolved.body
    assert "Never emit a blank-only / empty-only segment" in resolved.body
    assert "OMIT blank pages from every segment" in resolved.body
    assert "PAGE-OF-N (all document types)" in resolved.body
    assert "Repeating the same header on every page" in resolved.body


def test_sub_ledger_assign_prompt_in_catalog() -> None:
    from app.services.prompt_registry.catalog import get_prompt_definition

    defn = get_prompt_definition("llm.sub_ledger.assign.system")
    assert defn is not None
    assert defn.group == "Coding"
    body = resolve_system_prompt_text("llm.sub_ledger.assign.system")
    assert "ROLE — Sub-ledger Assignment Agent" in body
    assert "document_sub_ledger" in body
    assert "Parent ledger is FIXED" in body


@pytest.mark.asyncio
async def test_build_classify_system_prompt_uses_override(db_session: AsyncSession) -> None:
    await ensure_seeded(db_session)
    defn = next(p for p in PROMPT_CATALOG if p.key == "llm.classify.system")
    await create_version(
        db_session,
        "llm.classify.system",
        body=defn.default_body.replace(
            "You classify finance documents for accounts payable.",
            "CUSTOM CLASSIFY MARKER for accounts payable.",
        ),
    )
    await warm_prompt_cache(db_session)
    prompt = build_classify_system_prompt(OrgContext(country="AU"))
    assert "CUSTOM CLASSIFY MARKER" in prompt
    assert "Tenant context:" in prompt


@pytest.mark.asyncio
async def test_platform_prompts_api_super_admin(client, db_session: AsyncSession) -> None:
    _user, token = await seed_admin_user(
        db_session,
        email="super-prompt@test.example.com",
        role=UserRole.SUPER_ADMIN,
    )
    await db_session.commit()
    headers = tenant_auth_headers(token, TESTING_TENANT_UUID)

    listed = await client.get("/api/platform/prompts", headers=headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["data"]
    assert len(items) >= 12
    key = "llm.classify.system"
    detail = await client.get(f"/api/platform/prompts/{key}", headers=headers)
    assert detail.status_code == 200

    body = detail.json()["data"]["body"]
    created = await client.post(
        f"/api/platform/prompts/{key}/versions",
        headers=headers,
        json={"body": body + "\n# api-v2", "notes": "from api"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["data"]["version"] == 2

    versions = await client.get(f"/api/platform/prompts/{key}/versions", headers=headers)
    assert versions.status_code == 200
    assert versions.json()["data"]["items"][0]["version"] == 2

    activated = await client.post(
        f"/api/platform/prompts/{key}/versions/1/activate",
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["data"]["version"] == 1


@pytest.mark.asyncio
async def test_platform_prompts_api_rejects_non_super_admin(client, db_session: AsyncSession) -> None:
    _user, token = await seed_admin_user(
        db_session,
        email="admin-prompt@test.example.com",
        role=UserRole.ADMIN,
    )
    await db_session.commit()
    resp = await client.get(
        "/api/platform/prompts",
        headers=tenant_auth_headers(token, TESTING_TENANT_UUID),
    )
    assert resp.status_code == 403
