"""Phase 6 — move Graph messages to Processed / Exceptions folders."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
from app.services.email_ingestion import mailbox_api_path, mark_message_read
from app.services.graph_client import graph_request, is_graph_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)

FolderOutcome = Literal["processed", "exception"]

_SUCCESS_STATUSES = frozenset({InvoiceStatus.PROCESSED})


def folder_moves_enabled() -> bool:
    settings = get_settings()
    return settings.graph_folder_moves_enabled and is_graph_enabled()


@lru_cache
def _folder_id_cache_key(mailbox_email: str) -> tuple[str, str, str]:
    s = get_settings()
    return (mailbox_email, s.graph_processed_folder, s.graph_exceptions_folder)


def clear_folder_cache() -> None:
    _resolve_folder_ids.cache_clear()


def _list_inbox_child_folders(mailbox_email: str) -> list[dict]:
    data = graph_request(
        "GET",
        mailbox_api_path(mailbox_email, "/mailFolders/inbox/childFolders"),
    )
    return list(data.get("value") or [])


def _get_or_create_child_folder(mailbox_email: str, display_name: str) -> str:
    for folder in _list_inbox_child_folders(mailbox_email):
        if folder.get("displayName") == display_name:
            return str(folder["id"])
    created = graph_request(
        "POST",
        mailbox_api_path(mailbox_email, "/mailFolders/inbox/childFolders"),
        json_body={"displayName": display_name, "isHidden": False},
    )
    folder_id = str(created["id"])
    logger.info("graph_folder_created", display_name=display_name, folder_id=folder_id)
    return folder_id


@lru_cache
def _resolve_folder_ids(mailbox_email: str) -> dict[FolderOutcome, str]:
    _folder_id_cache_key(mailbox_email)
    settings = get_settings()
    return {
        "processed": _get_or_create_child_folder(
            mailbox_email, settings.graph_processed_folder
        ),
        "exception": _get_or_create_child_folder(
            mailbox_email, settings.graph_exceptions_folder
        ),
    }


def classify_message_outcome(statuses: list[InvoiceStatus]) -> FolderOutcome:
    """All invoices processed → Processed; otherwise → Exceptions."""
    if statuses and all(s in _SUCCESS_STATUSES for s in statuses):
        return "processed"
    return "exception"


def move_message_to_folder(
    message_id: str,
    outcome: FolderOutcome,
    *,
    mailbox_email: str,
) -> bool:
    """
    Move a message out of Inbox into Processed or Exceptions.

    Returns False when Graph is disabled, folder moves off, or API fails.
    """
    if not folder_moves_enabled():
        return mark_message_read(message_id, mailbox_email)

    try:
        folder_ids = _resolve_folder_ids(mailbox_email)
        destination_id = folder_ids[outcome]
        graph_request(
            "POST",
            mailbox_api_path(mailbox_email, f"/messages/{message_id}/move"),
            json_body={"destinationId": destination_id},
        )
        settings = get_settings()
        folder_name = (
            settings.graph_processed_folder
            if outcome == "processed"
            else settings.graph_exceptions_folder
        )
        logger.info(
            "message_moved",
            message_id=message_id,
            folder=folder_name,
            outcome=outcome,
        )
        return True
    except Exception as exc:
        logger.warning(
            "message_move_failed",
            message_id=message_id,
            outcome=outcome,
            error=str(exc),
            hint="Requires Mail.ReadWrite and mailbox access",
        )
        return mark_message_read(message_id, mailbox_email)


async def finalize_graph_messages(
    session: AsyncSession,
    message_ids: list[str],
    *,
    preskip_exceptions: dict[str, str] | None = None,
) -> int:
    """
    After pipeline run, move each polled message to Processed or Exceptions.

    preskip_exceptions: message_id → reason for emails skipped before ingest (no PDF).
    """
    if not message_ids:
        return 0

    preskip = preskip_exceptions or {}
    moved = 0
    settings = get_settings()

    from app.models.connected_mailbox import ConnectedMailbox

    for message_id in dict.fromkeys(message_ids):
        if message_id in preskip:
            outcome: FolderOutcome = "exception"
            reason = preskip[message_id]
            invoice_ids: list[int] = []
            mailbox_email = get_settings().graph_mailbox.strip()
        else:
            rows = (
                await session.execute(
                    select(Invoice).where(Invoice.email_message_id == message_id)
                )
            ).scalars().all()
            invoice_ids = [r.id for r in rows]
            statuses = [r.status for r in rows]
            outcome = classify_message_outcome(statuses)
            reason = "invoice_status" if rows else "no_invoices_ingested"
            mailbox_email = get_settings().graph_mailbox.strip()
            if rows and rows[0].connected_mailbox_id:
                mb = await session.get(ConnectedMailbox, rows[0].connected_mailbox_id)
                if mb:
                    mailbox_email = mb.email

        if not mailbox_email:
            continue

        if move_message_to_folder(message_id, outcome, mailbox_email=mailbox_email):
            moved += 1
            folder_name = (
                settings.graph_processed_folder
                if outcome == "processed"
                else settings.graph_exceptions_folder
            )
            await log_event(
                session,
                "email_moved",
                invoice_id=invoice_ids[0] if invoice_ids else None,
                detail={
                    "message_id": message_id,
                    "folder": folder_name,
                    "outcome": outcome,
                    "reason": reason,
                    "invoice_ids": invoice_ids,
                },
            )

    return moved
