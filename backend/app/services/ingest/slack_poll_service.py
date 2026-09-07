"""Poll Slack bot DMs for file uploads when Events API delivery is unreliable.

Used as a safety net alongside `/webhook/slack/events` (same ingest + dedupe path).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import db_session_with_rls, platform_lookup_session
from app.models.connected_slack import STATUS_CONNECTED, ConnectedSlackAccount
from app.services.ingest.slack_connection_service import (
    resolve_access_token,
    try_claim_event_id,
)
from app.services.ingest.slack_ingest_service import ingest_slack_message
from app.services.ingest.slack_web_client import (
    ParsedSlackMessage,
    SlackFileRef,
    _slack_api,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# First poll with no last_sync_at only looks this far back (avoid historical floods).
_DEFAULT_LOOKBACK = timedelta(hours=6)
_HISTORY_LIMIT = 30


def _message_event_id(*, channel: str, ts: str, file_ids: list[str]) -> str:
    files_key = ",".join(sorted(file_ids)) or "nofile"
    return f"poll:{channel}:{ts}:{files_key}"


def _parse_slack_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


async def _list_im_channels(access_token: str) -> list[dict]:
    channels: list[dict] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {
            "types": "im",
            "limit": 100,
            "exclude_archived": True,
        }
        if cursor:
            params["cursor"] = cursor
        data = await _slack_api(
            "conversations.list",
            access_token=access_token,
            params=params,
        )
        channels.extend(data.get("channels") or [])
        cursor = (
            ((data.get("response_metadata") or {}).get("next_cursor") or "").strip()
            or None
        )
        if not cursor:
            break
    return channels


async def _history_file_messages(
    access_token: str,
    *,
    channel: str,
    oldest: float | None,
) -> list[dict]:
    params: dict[str, str | int | float] = {
        "channel": channel,
        "limit": _HISTORY_LIMIT,
    }
    if oldest is not None:
        params["oldest"] = oldest
    data = await _slack_api(
        "conversations.history",
        access_token=access_token,
        params=params,
    )
    out: list[dict] = []
    for msg in data.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("bot_id") or msg.get("subtype"):
            continue
        if not (msg.get("files") or []):
            continue
        out.append(msg)
    return out


async def poll_connected_slack_account(
    connection_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    """Poll one workspace's DMs; returns counts for logging."""
    now = now or datetime.now(timezone.utc)
    stats: dict = {
        "connection_id": connection_id,
        "channels": 0,
        "candidates": 0,
        "ingested": 0,
        "skipped": 0,
        "queued": 0,
    }

    async with platform_lookup_session() as lookup:
        connection = await lookup.get(ConnectedSlackAccount, connection_id)
        if connection is None or connection.connection_status != STATUS_CONNECTED:
            return {**stats, "error": "not_connected"}
        try:
            token = resolve_access_token(connection)
        except Exception as exc:
            logger.error(
                "slack_poll_token_missing",
                connection_id=connection_id,
                error=str(exc),
            )
            return {**stats, "error": "token_missing"}
        team_id = connection.team_id
        tenant_id = connection.tenant_id
        bot_user_id = (connection.bot_user_id or "").strip()
        lookback_start = connection.last_sync_at

    stats["team_id"] = team_id

    if lookback_start is None:
        lookback_start = now - _DEFAULT_LOOKBACK
    elif lookback_start.tzinfo is None:
        lookback_start = lookback_start.replace(tzinfo=timezone.utc)
    oldest = (lookback_start - timedelta(minutes=2)).timestamp()

    try:
        ims = await _list_im_channels(token)
    except Exception as exc:
        logger.error(
            "slack_poll_list_ims_failed",
            connection_id=connection_id,
            error=str(exc),
        )
        return {**stats, "error": "list_ims_failed"}

    stats["channels"] = len(ims)
    all_invoice_ids: list[int] = []

    async with db_session_with_rls(tenant_id) as session:
        row = await session.get(ConnectedSlackAccount, connection_id)
        if row is None or row.connection_status != STATUS_CONNECTED:
            return {**stats, "error": "not_connected"}

        for ch in ims:
            channel_id = str(ch.get("id") or "")
            peer = str(ch.get("user") or "")
            if not channel_id or peer in {"USLACKBOT", bot_user_id}:
                continue

            try:
                messages = await _history_file_messages(
                    token,
                    channel=channel_id,
                    oldest=oldest,
                )
            except Exception as exc:
                logger.warning(
                    "slack_poll_history_failed",
                    connection_id=connection_id,
                    channel=channel_id,
                    error=str(exc),
                )
                continue

            for raw in messages:
                user_id = str(raw.get("user") or "")
                ts = str(raw.get("ts") or "")
                if not user_id or not ts or user_id == bot_user_id:
                    continue
                msg_at = _parse_slack_ts(ts)
                if msg_at is not None and msg_at < lookback_start - timedelta(minutes=2):
                    continue

                file_refs: list[SlackFileRef] = []
                file_ids: list[str] = []
                for f in raw.get("files") or []:
                    if not isinstance(f, dict):
                        continue
                    fid = str(f.get("id") or "")
                    if not fid:
                        continue
                    file_ids.append(fid)
                    file_refs.append(
                        SlackFileRef(
                            file_id=fid,
                            name=str(f.get("name") or "") or None,
                            mimetype=str(f.get("mimetype") or "") or None,
                            url_private=str(
                                f.get("url_private_download")
                                or f.get("url_private")
                                or ""
                            )
                            or None,
                            size=int(f["size"]) if f.get("size") is not None else None,
                        )
                    )
                if not file_refs:
                    continue

                stats["candidates"] += 1
                event_id = _message_event_id(
                    channel=channel_id,
                    ts=ts,
                    file_ids=file_ids,
                )
                if not await try_claim_event_id(
                    session,
                    event_id,
                    tenant_id=tenant_id,
                ):
                    stats["skipped"] += 1
                    continue

                parsed = ParsedSlackMessage(
                    event_id=event_id,
                    team_id=team_id,
                    channel=channel_id,
                    user_id=user_id,
                    text=str(raw.get("text") or "") or None,
                    ts=ts,
                    thread_ts=ts,
                    files=file_refs,
                )
                result = await ingest_slack_message(
                    session,
                    connection=row,
                    msg=parsed,
                    access_token=token,
                )
                ids = list(result.invoice_ids or [])
                if result.skipped_reason in {"duplicate", "duplicate_in_progress"}:
                    stats["skipped"] += 1
                else:
                    all_invoice_ids.extend(ids)
                    stats["ingested"] += int(result.ingested_count or 0)
                # Commit per message so a long poll does not hold one huge txn.
                await session.commit()
                row = await session.get(ConnectedSlackAccount, connection_id)
                if row is None or row.connection_status != STATUS_CONNECTED:
                    return {**stats, "error": "not_connected"}

        if row is not None:
            row.last_sync_at = now
            await session.commit()

    unique_ids = list(dict.fromkeys(all_invoice_ids))
    if unique_ids:
        # Await inline so uvicorn --reload cannot drop fire-and-forget tasks mid-run.
        from app.workers.tasks import process_invoices_batch_background

        await process_invoices_batch_background(unique_ids, tenant_id=tenant_id)
        stats["queued"] = len(unique_ids)

    return stats


async def poll_all_connected_slack_accounts() -> dict:
    """Poll every connected Slack workspace once."""
    async with platform_lookup_session() as sess:
        ids = list(
            (
                await sess.execute(
                    select(ConnectedSlackAccount.id).where(
                        ConnectedSlackAccount.connection_status == STATUS_CONNECTED,
                        ConnectedSlackAccount.access_token_encrypted.is_not(None),
                    )
                )
            ).scalars().all()
        )

    totals = {
        "accounts": len(ids),
        "ingested": 0,
        "queued": 0,
        "skipped": 0,
        "candidates": 0,
        "errors": 0,
    }
    for connection_id in ids:
        result = await poll_connected_slack_account(connection_id)
        if result.get("error"):
            totals["errors"] += 1
        totals["ingested"] += int(result.get("ingested") or 0)
        totals["queued"] += int(result.get("queued") or 0)
        totals["skipped"] += int(result.get("skipped") or 0)
        totals["candidates"] += int(result.get("candidates") or 0)
        logger.info("slack_poll_account_done", **result)

    return totals
