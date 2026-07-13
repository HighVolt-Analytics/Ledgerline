"""Run poll+ingest for vishnu@highvolt.tech (HighVolt Analytics tenant)."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session_factory
from app.models.connected_mailbox import ConnectedMailbox
from app.services.ingest.mailbox_poll import poll_mailbox_and_ingest


TENANT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")


async def main() -> None:
    async with async_session_factory() as session:
        mb = (
            await session.execute(
                select(ConnectedMailbox).where(
                    ConnectedMailbox.email == "vishnu@highvolt.tech",
                    ConnectedMailbox.tenant_id == TENANT_ID,
                )
            )
        ).scalars().first()
        if not mb:
            print("mailbox not found")
            return

        print("polling mailbox_id", mb.id, "tenant", mb.tenant_id)
        result = await poll_mailbox_and_ingest(
            session,
            mailbox_id=mb.id,
            tenant_id=mb.tenant_id,
        )
        await session.commit()
        print(
            "ingested_count", result.ingested_count,
            "message_ids", result.message_ids,
            "preskip", dict(result.preskip_exceptions),
        )


if __name__ == "__main__":
    asyncio.run(main())
