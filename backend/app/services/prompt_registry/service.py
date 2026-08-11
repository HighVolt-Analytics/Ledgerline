"""Platform prompt registry: seed, version history, resolve active body."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_prompt import PlatformPromptActive, PlatformPromptVersion
from app.services.prompt_registry.catalog import (
    PROMPT_BY_KEY,
    PROMPT_CATALOG,
    PromptDefinition,
    catalog_default_body,
    get_prompt_definition,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 60.0
# Serialize seed/upgrade within one process (parallel invoice pipelines share uvicorn).
_seed_lock = asyncio.Lock()


@dataclass
class _CacheEntry:
    body: str
    version: int | str
    expires_at: float


_cache: dict[str, _CacheEntry] = {}


@dataclass(frozen=True)
class ResolvedPrompt:
    body: str
    version: int | str
    prompt_key: str


def invalidate_prompt_cache(key: str | None = None) -> None:
    if key is None:
        _cache.clear()
        return
    _cache.pop(key, None)


def _set_cache(key: str, body: str, version: int | str) -> None:
    _cache[key] = _CacheEntry(
        body=body,
        version=version,
        expires_at=time.monotonic() + _CACHE_TTL_SECONDS,
    )


def _cache_get(key: str) -> _CacheEntry | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    if entry.expires_at < time.monotonic():
        _cache.pop(key, None)
        return None
    return entry


async def ensure_seeded(session: AsyncSession) -> int:
    """Insert v1 + active pointer for any catalog key missing from DB. Returns rows created."""
    async with _seed_lock:
        return await _ensure_seeded_unlocked(session)


async def _ensure_seeded_unlocked(session: AsyncSession) -> int:
    created = 0
    existing_keys = set(
        (
            await session.execute(select(PlatformPromptVersion.prompt_key).distinct())
        ).scalars().all()
    )
    for defn in PROMPT_CATALOG:
        if defn.key in existing_keys:
            continue
        try:
            async with session.begin_nested():
                row = PlatformPromptVersion(
                    prompt_key=defn.key,
                    version=1,
                    body=defn.default_body,
                    notes="Seeded from code catalog",
                )
                session.add(row)
                await session.flush()
                session.add(
                    PlatformPromptActive(
                        prompt_key=defn.key,
                        active_version_id=row.id,
                    )
                )
                await session.flush()
            created += 1
        except IntegrityError:
            # Another coroutine / worker seeded this key first.
            logger.info("platform_prompt_seed_race", prompt_key=defn.key)
            continue
    if created:
        invalidate_prompt_cache()
    synced = await _sync_catalog_prompt_upgrades_unlocked(session)
    return created + synced


def _catalog_upgrade_markers() -> dict[str, tuple[str, ...]]:
    from app.services.invoice.vision_header_schema import VISION_HEADER_PROMPT_MARKERS

    return {
        "vision.header_extract.system": VISION_HEADER_PROMPT_MARKERS,
        "vision.type_suggest.system": (
            "TYPE SUGGEST — understand the document",
            "document_summary",
            "document_role_hints",
            "Do not extract amounts",
            "Do not map to a catalogue DT code",
            "canonical_document_type",
            "SELF-CHECK BEFORE RETURNING",
        ),
        "vision.dt_map_fallback.system": (
            "You map a vision document understanding (title + summary) to ONE Rule Book catalogue code",
            "document_summary",
            "document_role_hints",
            "NEVER invent a DT code",
            "Prefer \"\" over a weak guess",
            "When two catalogue rows fit equally well even after reading the summary, return \"\"",
            "few_shot_examples",
            "human_confirmed_dt",
            "DESPATCH ADVICE",
            "SELF-CHECK BEFORE RETURNING",
        ),
        "vision.understand.system": (
            "Foundry-style readability gate",
            "Proof of Delivery",
            "Do not require invoice amounts or line items",
            "Do not reject a readable shipping, delivery, packing, receipt, handover, or",
            "Do not use a catalogue",
            "handover slips, letters of authorization",
        ),
        "llm.currency.system": (
            "You are a Currency Detection Agent",
            "ZERO tolerance for error",
            "HR1. NEVER assign a currency ISO code from a bare",
            "PHASE 1 — SIGNAL HARVEST",
            "Prefer \"UNCERTAIN\" over a wrong answer",
        ),
        "llm.field_translate.system": (
            "You are a Field Translation Agent",
            "source_language",
            "line_descriptions",
            "already_english",
            "SELF-CHECK BEFORE RETURNING",
        ),
        "llm.extract.sparse_hint": (
            "Sparse OCR / image-backed extract",
            "Burmese/Myanmar",
            "line_items.description",
            "Never use row indexes or phone digits as the",
        ),
        "llm.sub_ledger.assign.system": (
            "ROLE — Sub-ledger Assignment Agent",
            "Parent ledger is FIXED",
            "document_sub_ledger",
            "line_suggestions",
            "sub_ledger_catalogue",
            "Prefer \"\" over a weak guess",
            "SELF-CHECK BEFORE RETURNING",
        ),
        # Distinctive markers from the v2 hardened segment prompt (stale seeds lack these).
        "pdf.segment.system": (
            "ROLE — Document Splitting Agent (page-range mode) — v2 (hardened)",
            "KNOWN HARD LIMITATION",
            "SEPARATOR / NON-DOCUMENT PAGES (MUST SKIP AS DOCUMENTS)",
            'WHAT "ONE DOCUMENT" MEANS',
            "CORE METHOD — WINDOW … i-1 | i | i+1 | i+2 …",
            "DECISION ORDER (mandatory for every page i)",
            "(1) LOOK BACK — does a NEW document start at i?",
            "(2) LOOK AHEAD — does this page OPEN / CONTINUE a multi-page single document?",
            "(3) LOOK AHEAD FOR TYPE CHANGE — when to CLOSE the current run",
            "Page 0: SKIP this step (no previous)",
            "CLASSIFICATION HEURISTICS H1–H3",
            "PHASE 3 — GROUPING (G1–G4)",
            "FAILURE MODES (detect in reasoning; do not silently collapse)",
            "DOCUMENT TYPE TAXONOMY",
            "Prefer correct single-document boundaries",
            "BLANK / EMPTY PAGES (MUST SKIP AS DOCUMENTS)",
            "Never emit a blank-only / empty-only segment",
            "OMIT blank pages from every segment",
            "PAGE-OF-N (all document types)",
            "Repeating the same header on every page",
            "R11. Every page must be accounted for",
            "Run the R11 coverage self-check before returning output",
            "E23. Reissue/duplicate/replacement document",
            "E22. Same template/layout, different issuing company",
        ),
    }


def _body_satisfies_markers(body: str, markers: tuple[str, ...]) -> bool:
    return bool(body) and all(marker in body for marker in markers)


async def _activate_prompt_version(
    session: AsyncSession,
    active: PlatformPromptActive,
    row: PlatformPromptVersion,
) -> None:
    active.active_version_id = row.id
    await session.flush()
    _set_cache(row.prompt_key, row.body, row.version)


async def sync_catalog_prompt_upgrades(session: AsyncSession) -> int:
    """Publish catalog default when an active seed is missing required markers.

    Avoids stale DB seeds after code catalog updates (e.g. new JSON keys).
    Race-safe under parallel invoice pipelines (savepoints + max version).
    """
    async with _seed_lock:
        return await _sync_catalog_prompt_upgrades_unlocked(session)


async def _sync_catalog_prompt_upgrades_unlocked(session: AsyncSession) -> int:
    upgraded = 0
    for key, markers in _catalog_upgrade_markers().items():
        defn = get_prompt_definition(key)
        if defn is None:
            continue
        active = await session.get(PlatformPromptActive, key)
        if active is None:
            continue
        version_row = await session.get(PlatformPromptVersion, active.active_version_id)
        if version_row is None:
            continue
        body = version_row.body or ""
        catalog_body = defn.default_body
        if body.strip() == catalog_body.strip():
            continue
        if _body_satisfies_markers(body, markers):
            continue

        # Prefer activating an existing version that already has the catalog body / markers.
        existing_rows = (
            await session.execute(
                select(PlatformPromptVersion)
                .where(PlatformPromptVersion.prompt_key == key)
                .order_by(PlatformPromptVersion.version.desc())
            )
        ).scalars().all()
        match = next(
            (
                row
                for row in existing_rows
                if (row.body or "").strip() == catalog_body.strip()
                or _body_satisfies_markers(row.body or "", markers)
            ),
            None,
        )
        if match is not None:
            if active.active_version_id != match.id:
                await _activate_prompt_version(session, active, match)
                upgraded += 1
            continue

        max_version = (
            await session.execute(
                select(func.max(PlatformPromptVersion.version)).where(
                    PlatformPromptVersion.prompt_key == key
                )
            )
        ).scalar_one_or_none()
        next_version = int(max_version or 0) + 1
        row = PlatformPromptVersion(
            prompt_key=key,
            version=next_version,
            body=catalog_body,
            notes="Auto-synced from code catalog (missing field markers)",
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
                active.active_version_id = row.id
                await session.flush()
            upgraded += 1
            _set_cache(key, row.body, row.version)
        except IntegrityError:
            # Concurrent upgrade inserted the same (key, version); activate the winner.
            logger.info(
                "platform_prompt_upgrade_race",
                prompt_key=key,
                attempted_version=next_version,
            )
            winner = (
                await session.execute(
                    select(PlatformPromptVersion)
                    .where(PlatformPromptVersion.prompt_key == key)
                    .order_by(PlatformPromptVersion.version.desc())
                )
            ).scalars().first()
            if winner is not None and (
                (winner.body or "").strip() == catalog_body.strip()
                or _body_satisfies_markers(winner.body or "", markers)
            ):
                if active.active_version_id != winner.id:
                    await _activate_prompt_version(session, active, winner)
                    upgraded += 1
            continue
    if upgraded:
        invalidate_prompt_cache()
    return upgraded


async def warm_prompt_cache(session: AsyncSession) -> None:
    """Load all active prompt bodies into the process cache."""
    await ensure_seeded(session)
    result = await session.execute(
        select(PlatformPromptActive, PlatformPromptVersion)
        .join(
            PlatformPromptVersion,
            PlatformPromptActive.active_version_id == PlatformPromptVersion.id,
        )
    )
    for active, version_row in result.all():
        _set_cache(active.prompt_key, version_row.body, version_row.version)


def resolve_system_prompt(key: str, **format_kwargs: Any) -> ResolvedPrompt:
    """Sync resolve: active cached body, else code catalog default."""
    if key not in PROMPT_BY_KEY:
        raise KeyError(f"Unknown prompt key: {key}")

    entry = _cache_get(key)
    if entry is not None:
        body = entry.body
        version: int | str = entry.version
    else:
        body = catalog_default_body(key) or ""
        version = "code"
        _set_cache(key, body, version)

    # Prefer code catalog when a cached seed is missing required field markers.
    markers = _catalog_upgrade_markers().get(key)
    if markers and body and not all(marker in body for marker in markers):
        catalog_body = catalog_default_body(key) or ""
        if catalog_body and all(marker in catalog_body for marker in markers):
            body = catalog_body
            version = "code"

    if format_kwargs:
        body = body.format(**format_kwargs)
    return ResolvedPrompt(body=body, version=version, prompt_key=key)


def resolve_system_prompt_text(key: str, **format_kwargs: Any) -> str:
    return resolve_system_prompt(key, **format_kwargs).body


async def list_prompt_summaries(session: AsyncSession) -> list[dict[str, Any]]:
    await ensure_seeded(session)
    await warm_prompt_cache(session)
    active_map = await _active_version_map(session)
    items: list[dict[str, Any]] = []
    for defn in PROMPT_CATALOG:
        active = active_map.get(defn.key)
        if active:
            body, version, updated_at, notes = active
            is_overridden = version > 1 or body != defn.default_body
        else:
            body, version, updated_at, notes = defn.default_body, None, None, None
            is_overridden = False
        items.append(
            {
                "key": defn.key,
                "label": defn.label,
                "group": defn.group,
                "description": defn.description,
                "placeholders": list(defn.placeholders),
                "default_body": defn.default_body,
                "body": body,
                "version": version,
                "is_overridden": is_overridden,
                "updated_at": updated_at,
                "notes": notes,
            }
        )
    return items


async def get_prompt_detail(session: AsyncSession, key: str) -> dict[str, Any] | None:
    defn = get_prompt_definition(key)
    if defn is None:
        return None
    await ensure_seeded(session)
    active_map = await _active_version_map(session)
    active = active_map.get(key)
    if active:
        body, version, updated_at, notes = active
        is_overridden = version > 1 or body != defn.default_body
    else:
        body, version, updated_at, notes = defn.default_body, None, None, None
        is_overridden = False
    return {
        "key": defn.key,
        "label": defn.label,
        "group": defn.group,
        "description": defn.description,
        "placeholders": list(defn.placeholders),
        "default_body": defn.default_body,
        "body": body,
        "version": version,
        "is_overridden": is_overridden,
        "updated_at": updated_at,
        "notes": notes,
    }


async def list_versions(session: AsyncSession, key: str) -> list[dict[str, Any]] | None:
    if get_prompt_definition(key) is None:
        return None
    await ensure_seeded(session)
    active = await session.get(PlatformPromptActive, key)
    active_id = active.active_version_id if active else None
    rows = (
        await session.execute(
            select(PlatformPromptVersion)
            .where(PlatformPromptVersion.prompt_key == key)
            .order_by(PlatformPromptVersion.version.desc())
        )
    ).scalars().all()
    return [
        {
            "version": row.version,
            "body": row.body,
            "notes": row.notes,
            "created_at": row.created_at,
            "created_by_user_id": row.created_by_user_id,
            "is_active": row.id == active_id,
        }
        for row in rows
    ]


def _validate_body(defn: PromptDefinition, body: str) -> str | None:
    text = (body or "").strip()
    if not text:
        return "Prompt body must not be empty"
    for placeholder in defn.placeholders:
        token = "{" + placeholder + "}"
        if token not in body:
            return f"Prompt body must include placeholder {token}"
    return None


async def create_version(
    session: AsyncSession,
    key: str,
    *,
    body: str,
    notes: str | None = None,
    user_id: int | None = None,
) -> PlatformPromptVersion:
    defn = get_prompt_definition(key)
    if defn is None:
        raise KeyError(key)
    err = _validate_body(defn, body)
    if err:
        raise ValueError(err)
    await ensure_seeded(session)
    max_version = (
        await session.execute(
            select(PlatformPromptVersion.version)
            .where(PlatformPromptVersion.prompt_key == key)
            .order_by(PlatformPromptVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_version = int(max_version or 0) + 1
    row = PlatformPromptVersion(
        prompt_key=key,
        version=next_version,
        body=body,
        notes=(notes or "").strip() or None,
        created_by_user_id=user_id,
    )
    session.add(row)
    await session.flush()
    active = await session.get(PlatformPromptActive, key)
    if active is None:
        session.add(
            PlatformPromptActive(
                prompt_key=key,
                active_version_id=row.id,
                updated_by_user_id=user_id,
            )
        )
    else:
        active.active_version_id = row.id
        active.updated_by_user_id = user_id
    await session.flush()
    _set_cache(key, row.body, row.version)
    return row


async def activate_version(
    session: AsyncSession,
    key: str,
    version: int,
    *,
    user_id: int | None = None,
) -> PlatformPromptVersion:
    if get_prompt_definition(key) is None:
        raise KeyError(key)
    await ensure_seeded(session)
    row = (
        await session.execute(
            select(PlatformPromptVersion).where(
                PlatformPromptVersion.prompt_key == key,
                PlatformPromptVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"Version {version} not found for {key}")
    active = await session.get(PlatformPromptActive, key)
    if active is None:
        session.add(
            PlatformPromptActive(
                prompt_key=key,
                active_version_id=row.id,
                updated_by_user_id=user_id,
            )
        )
    else:
        active.active_version_id = row.id
        active.updated_by_user_id = user_id
    await session.flush()
    _set_cache(key, row.body, row.version)
    return row


async def _active_version_map(
    session: AsyncSession,
) -> dict[str, tuple[str, int, Any, str | None]]:
    result = await session.execute(
        select(PlatformPromptActive, PlatformPromptVersion)
        .join(
            PlatformPromptVersion,
            PlatformPromptActive.active_version_id == PlatformPromptVersion.id,
        )
    )
    out: dict[str, tuple[str, int, Any, str | None]] = {}
    for active, version_row in result.all():
        out[active.prompt_key] = (
            version_row.body,
            version_row.version,
            active.updated_at,
            version_row.notes,
        )
    return out
