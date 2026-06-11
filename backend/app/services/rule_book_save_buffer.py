"""Server-side debounced commit for rule book saves (audit + remap once per edit burst)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.audit_service import log_event
from app.services.master_data_service import sync_masters_to_config_file
from app.services.remap_service import remap_invoices_for_org
from app.services.rule_book_audit import (
    diff_rule_book_config,
    filter_auditable_rule_book_changes,
    is_duplicate_rule_book_update,
    log_rule_book_updated,
    normalize_rule_book_for_diff,
    rule_book_changes_are_auditable,
    summarize_rule_book_config,
)
from app.services.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

_buffer_lock = asyncio.Lock()
_buffers: dict[int, PendingRuleBookSave] = {}


@dataclass
class PendingRuleBookSave:
    org_id: int
    payload: RuleBookConfigPayload
    after_raw: dict[str, Any]
    before_raw: dict[str, Any]
    actor_name: str | None
    actor_email: str | None
    client_ip: str | None
    timer_handle: asyncio.TimerHandle | None = None


def _debounce_seconds() -> float:
    return max(0.0, get_settings().rule_book_save_debounce_ms / 1000.0)


def get_buffered_rule_book_raw(org_id: int) -> dict[str, Any] | None:
    pending = _buffers.get(org_id)
    return dict(pending.after_raw) if pending else None


def clear_rule_book_save_buffers() -> None:
    for pending in _buffers.values():
        if pending.timer_handle is not None:
            pending.timer_handle.cancel()
    _buffers.clear()


async def flush_rule_book_save_buffer(
    org_id: int,
    *,
    db: AsyncSession | None = None,
) -> None:
    """Commit any pending save immediately (used by tests and shutdown hooks)."""
    async with _buffer_lock:
        pending = _buffers.pop(org_id, None)
        if pending is not None and pending.timer_handle is not None:
            pending.timer_handle.cancel()
    if pending is not None:
        await commit_rule_book_save(pending, db=db)


async def schedule_rule_book_save(
    *,
    org_id: int,
    payload: RuleBookConfigPayload,
    after_raw: dict[str, Any],
    actor_name: str | None,
    actor_email: str | None,
    client_ip: str | None,
    db: AsyncSession | None = None,
) -> None:
    """Buffer a validated save; flush after the debounce window."""
    async with _buffer_lock:
        existing = _buffers.get(org_id)
        if existing is not None:
            before_raw = existing.before_raw
            if existing.timer_handle is not None:
                existing.timer_handle.cancel()
        else:
            before_raw = load_rule_book_config_dict(org_id)

        pending = PendingRuleBookSave(
            org_id=org_id,
            payload=payload,
            after_raw=after_raw,
            before_raw=before_raw,
            actor_name=actor_name,
            actor_email=actor_email,
            client_ip=client_ip,
        )

        delay = _debounce_seconds()
        if delay <= 0:
            await commit_rule_book_save(pending, db=db)
            return

        _buffers[org_id] = pending
        loop = asyncio.get_running_loop()

        def _on_timer() -> None:
            asyncio.create_task(_flush_from_timer(org_id))

        pending.timer_handle = loop.call_later(delay, _on_timer)


async def _flush_from_timer(org_id: int) -> None:
    async with _buffer_lock:
        pending = _buffers.pop(org_id, None)
    if pending is None:
        return
    try:
        async with async_session_factory() as session:
            await commit_rule_book_save(pending, db=session)
            await session.commit()
    except Exception:
        logger.exception("rule_book_save_flush_failed", org_id=org_id)


async def _commit_rule_book_db_side_effects(
    session: AsyncSession,
    pending: PendingRuleBookSave,
    *,
    auditable_changes: dict[str, Any],
    changes: dict[str, Any],
    before_norm: dict[str, Any],
    after_norm: dict[str, Any],
) -> None:
    if await is_duplicate_rule_book_update(session, pending.org_id, after_norm):
        logger.info(
            "rule_book_save_suppressed_duplicate",
            org_id=pending.org_id,
        )
        return

    await sync_masters_to_config_file(session, pending.org_id)

    if rule_book_changes_are_auditable(
        changes,
        before=before_norm,
        after=after_norm,
    ):
        await log_rule_book_updated(
            session,
            org_id=pending.org_id,
            after_config=after_norm,
            detail={
                "before": summarize_rule_book_config(pending.before_raw),
                "after": summarize_rule_book_config(pending.after_raw),
                "changes": auditable_changes,
            },
            actor_name=pending.actor_name,
            actor_email=pending.actor_email,
            client_ip=pending.client_ip,
        )

    remap_result = await remap_invoices_for_org(session, org_id=pending.org_id)
    if remap_result.updated:
        await log_event(
            session,
            "invoices_remapped",
            org_id=pending.org_id,
            detail={
                "updated": remap_result.updated,
                "total": remap_result.total,
                "invoice_ids": remap_result.invoice_ids[:200],
                "invoice_ids_truncated": len(remap_result.invoice_ids) > 200,
            },
            actor_name=pending.actor_name,
            actor_email=pending.actor_email,
            client_ip=pending.client_ip,
        )


async def commit_rule_book_save(
    pending: PendingRuleBookSave,
    *,
    db: AsyncSession | None = None,
) -> bool:
    """Persist config, audit real changes, and remap invoices once. Returns True if committed."""
    before_norm = normalize_rule_book_for_diff(pending.before_raw)
    after_norm = normalize_rule_book_for_diff(pending.after_raw)
    if before_norm == after_norm:
        return False

    changes = diff_rule_book_config(before_norm, after_norm)
    auditable_changes = filter_auditable_rule_book_changes(
        changes,
        before=before_norm,
        after=after_norm,
    )

    save_rule_book_config(pending.payload, pending.org_id)

    if db is not None:
        await _commit_rule_book_db_side_effects(
            db,
            pending,
            auditable_changes=auditable_changes,
            changes=changes,
            before_norm=before_norm,
            after_norm=after_norm,
        )
        return True

    async with async_session_factory() as session:
        await _commit_rule_book_db_side_effects(
            session,
            pending,
            auditable_changes=auditable_changes,
            changes=changes,
            before_norm=before_norm,
            after_norm=after_norm,
        )
        await session.commit()
    return True
