"""Phase 6 — move Graph messages to Processed / Exceptions folders."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.tenant_ids import parse_tenant_id
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.ingest.email_ingestion import mailbox_api_path, mark_message_read
from app.services.ingest.graph_client import graph_request, is_graph_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)

FolderOutcome = Literal["processed", "exception"]

# Folder routing treats duplicate shadows as done — otherwise Exceptions re-poll
# keeps re-fetching the same message and creating more duplicate rows.
_SUCCESS_STATUSES = frozenset({InvoiceStatus.PROCESSED, InvoiceStatus.DUPLICATE_SKIPPED})
# Only permanent duplicates go to Processed. Capture-rule misses stay in Exceptions
# so the 48h Exceptions re-poll can retry after rules are fixed.
_PRESKIP_PROCESSED_REASONS = frozenset({"message_already_imported"})


def folder_moves_enabled() -> bool:
    settings = get_settings()
    return settings.graph_folder_moves_enabled and is_graph_enabled()


def clear_folder_cache() -> None:
    """No-op — folder IDs are resolved per request with delegated tokens."""
    return None


def _list_inbox_child_folders(
    mailbox_email: str,
    *,
    access_token: str | None = None,
) -> list[dict]:
    data = graph_request(
        "GET",
        mailbox_api_path(mailbox_email, "/mailFolders/inbox/childFolders"),
        access_token=access_token,
    )
    return list(data.get("value") or [])


def get_child_folder_id(
    mailbox_email: str,
    display_name: str,
    *,
    access_token: str | None = None,
) -> str | None:
    """Return Graph folder id for an Inbox child folder (e.g. Exceptions, Processed)."""
    for folder in _list_inbox_child_folders(mailbox_email, access_token=access_token):
        if folder.get("displayName") == display_name:
            folder_id = folder.get("id")
            return str(folder_id) if folder_id else None
    return None


def _get_or_create_child_folder(
    mailbox_email: str,
    display_name: str,
    *,
    access_token: str | None = None,
) -> str:
    for folder in _list_inbox_child_folders(mailbox_email, access_token=access_token):
        if folder.get("displayName") == display_name:
            return str(folder["id"])
    created = graph_request(
        "POST",
        mailbox_api_path(mailbox_email, "/mailFolders/inbox/childFolders"),
        json_body={"displayName": display_name, "isHidden": False},
        access_token=access_token,
    )
    folder_id = str(created["id"])
    logger.info("graph_folder_created", display_name=display_name, folder_id=folder_id)
    return folder_id


def _resolve_folder_ids(
    mailbox_email: str,
    access_token: str | None = None,
) -> dict[FolderOutcome, str]:
    settings = get_settings()
    return {
        "processed": _get_or_create_child_folder(
            mailbox_email,
            settings.graph_processed_folder,
            access_token=access_token,
        ),
        "exception": _get_or_create_child_folder(
            mailbox_email,
            settings.graph_exceptions_folder,
            access_token=access_token,
        ),
    }


def classify_message_outcome(statuses: list[InvoiceStatus]) -> FolderOutcome:
    """All invoices done (processed or duplicate) → Processed; otherwise → Exceptions."""
    if statuses and all(s in _SUCCESS_STATUSES for s in statuses):
        return "processed"
    return "exception"


def move_message_to_folder(
    message_id: str,
    outcome: FolderOutcome,
    *,
    mailbox_email: str,
    access_token: str | None = None,
) -> str | None:
    """
    Move a message out of Inbox into Processed or Exceptions.

    Returns the post-move Graph message id when the move succeeds (may differ from
    the input id if ImmutableId was not honored), True-ish mark-read fallback as
    the same message_id, or None on failure.
    """
    if not folder_moves_enabled():
        if mark_message_read(message_id, mailbox_email, access_token=access_token):
            return message_id
        return None

    try:
        folder_ids = _resolve_folder_ids(mailbox_email, access_token)
        destination_id = folder_ids[outcome]
        moved = graph_request(
            "POST",
            mailbox_api_path(mailbox_email, f"/messages/{message_id}/move"),
            json_body={"destinationId": destination_id},
            access_token=access_token,
        )
        settings = get_settings()
        folder_name = (
            settings.graph_processed_folder
            if outcome == "processed"
            else settings.graph_exceptions_folder
        )
        new_id = str(moved.get("id") or message_id)
        logger.info(
            "message_moved",
            message_id=message_id,
            new_message_id=new_id if new_id != message_id else None,
            folder=folder_name,
            outcome=outcome,
        )
        return new_id
    except Exception as exc:
        logger.warning(
            "message_move_failed",
            message_id=message_id,
            outcome=outcome,
            error=str(exc),
            hint="Requires Mail.ReadWrite and mailbox access",
        )
        if mark_message_read(message_id, mailbox_email, access_token=access_token):
            return message_id
        return None


async def finalize_graph_messages(
    session: AsyncSession,
    message_ids: list[str],
    *,
    tenant_id: str | int | None = None,
    preskip_exceptions: dict[str, str] | None = None,
    message_mailbox_emails: dict[str, str] | None = None,
    message_graph_ids: dict[str, str] | None = None,
) -> int:
    """
    Persist mailbox_messages outcomes; move Graph messages when enabled.

    Gmail uses the same DB outcomes without Outlook folder moves.
    Graph folder moves remain a side effect of the DB outcome.
    """
    if not message_ids:
        return 0

    preskip = preskip_exceptions or {}
    mailbox_by_message = message_mailbox_emails or {}
    graph_ids = message_graph_ids or {}
    moved = 0
    settings = get_settings()
    scoped_tenant_id = parse_tenant_id(tenant_id)

    from app.models.connected_mailbox import MAIL_PROVIDER_GOOGLE, ConnectedMailbox
    from app.models.mailbox_message import (
        OUTCOME_EXCEPTION,
        OUTCOME_PROCESSED,
        OUTCOME_SKIPPED,
    )
    from app.services.ingest.mailbox_message_service import (
        outcome_for_preskip_reason,
        set_mailbox_message_outcome,
        upsert_pending_mailbox_message,
    )
    from app.services.ingest.mailbox_oauth_service import resolve_mailbox_access_token

    for message_id in dict.fromkeys(message_ids):
        access_token: str | None = None
        rows: list[Invoice] = []
        api_message_id = graph_ids.get(message_id) or message_id
        skip_reason: str | None = None
        preskip_reason = preskip.get(message_id)
        if preskip_reason is not None:
            outcome: FolderOutcome = (
                "processed"
                if preskip_reason in _PRESKIP_PROCESSED_REASONS
                else "exception"
            )
            db_outcome = outcome_for_preskip_reason(preskip_reason)
            reason = preskip_reason
            invoice_ids: list[int] = []
            mailbox_email = (
                (mailbox_by_message.get(message_id) or "").strip()
                or get_settings().graph_mailbox.strip()
            )
        else:
            stmt = select(Invoice).where(Invoice.email_message_id == message_id)
            if scoped_tenant_id is not None:
                stmt = stmt.where(Invoice.tenant_id == scoped_tenant_id)
            rows = list((await session.execute(stmt)).scalars().all())
            invoice_ids = [r.id for r in rows]
            statuses = [r.status for r in rows]
            outcome = classify_message_outcome(statuses)
            db_outcome = (
                OUTCOME_PROCESSED if outcome == "processed" else OUTCOME_EXCEPTION
            )
            reason = "invoice_status" if rows else "no_invoices_ingested"
            mailbox_email = (
                (mailbox_by_message.get(message_id) or "").strip()
                or get_settings().graph_mailbox.strip()
            )
            if rows and rows[0].connected_mailbox_id:
                mb = await session.get(ConnectedMailbox, rows[0].connected_mailbox_id)
                if mb:
                    mailbox_email = mb.email

        mb_row: ConnectedMailbox | None = None
        if rows and rows[0].connected_mailbox_id:
            mb_row = await session.get(ConnectedMailbox, rows[0].connected_mailbox_id)
        elif mailbox_email:
            stmt = select(ConnectedMailbox).where(ConnectedMailbox.email == mailbox_email)
            # Same mailbox email can exist on multiple tenants — always scope.
            if scoped_tenant_id is not None:
                stmt = stmt.where(ConnectedMailbox.tenant_id == scoped_tenant_id)
            elif rows:
                stmt = stmt.where(ConnectedMailbox.tenant_id == rows[0].tenant_id)
            mb_row = (await session.execute(stmt)).scalars().first()

        if mb_row is not None:
            tenant_for_row = scoped_tenant_id or mb_row.tenant_id
            await upsert_pending_mailbox_message(
                session,
                tenant_id=tenant_for_row,
                connected_mailbox_id=mb_row.id,
                provider=mb_row.mail_provider,
                stable_message_id=message_id,
                provider_message_id=api_message_id,
            )
            skip_reason = (
                preskip_reason
                if db_outcome in {OUTCOME_SKIPPED, OUTCOME_EXCEPTION} and preskip_reason
                else (reason if db_outcome != OUTCOME_PROCESSED else None)
            )
            # Prefer Phase 1 taxonomy strings when we already audited via ingest_skipped.
            if preskip_reason in {
                "integrity_error",
                "ingest_error",
            }:
                skip_reason = (
                    "ingest_integrity_error"
                    if preskip_reason == "integrity_error"
                    else "ingest_message_failed"
                )
            await set_mailbox_message_outcome(
                session,
                connected_mailbox_id=mb_row.id,
                stable_message_id=message_id,
                outcome=db_outcome,
                skip_reason=skip_reason,
                provider_message_id=api_message_id,
                folder_synced=False,
            )

        is_gmail = mb_row is not None and mb_row.mail_provider == MAIL_PROVIDER_GOOGLE
        do_folder_move = (
            not is_gmail
            and folder_moves_enabled()
            and bool(mailbox_email)
        )

        if mb_row and mb_row.is_pollable and do_folder_move:
            try:
                access_token = await resolve_mailbox_access_token(session, mb_row)
            except Exception:
                access_token = None

        if not mailbox_email and not is_gmail:
            continue

        if is_gmail:
            # Gmail parity: DB outcome is the lifecycle; no Outlook folders.
            if mb_row is not None:
                await set_mailbox_message_outcome(
                    session,
                    connected_mailbox_id=mb_row.id,
                    stable_message_id=message_id,
                    outcome=db_outcome,
                    skip_reason=skip_reason if db_outcome != OUTCOME_PROCESSED else None,
                    provider_message_id=api_message_id,
                    folder_synced=True,
                )
            continue

        if not do_folder_move:
            continue

        new_graph_id = move_message_to_folder(
            api_message_id,
            outcome,
            mailbox_email=mailbox_email,
            access_token=access_token,
        )
        if new_graph_id:
            moved += 1
            if mb_row is not None:
                await set_mailbox_message_outcome(
                    session,
                    connected_mailbox_id=mb_row.id,
                    stable_message_id=message_id,
                    outcome=db_outcome,
                    skip_reason=skip_reason if db_outcome != OUTCOME_PROCESSED else None,
                    provider_message_id=new_graph_id,
                    folder_synced=True,
                )
            # Legacy rows stored the mutable Graph id as email_message_id. If Graph
            # rewrote that id on move, keep known_message_ids in sync. Do not overwrite
            # a stable RFC internetMessageId (message_id != api_message_id) with a Graph id.
            if rows and new_graph_id != api_message_id:
                for row in rows:
                    if row.email_message_id == api_message_id:
                        row.email_message_id = new_graph_id
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
                    "graph_message_id": api_message_id,
                    "new_graph_message_id": (
                        new_graph_id if new_graph_id != api_message_id else None
                    ),
                    "folder": folder_name,
                    "outcome": outcome,
                    "reason": reason,
                    "invoice_ids": invoice_ids,
                },
            )

    return moved
