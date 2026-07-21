"""Backfill legacy understood-path holds still stored as awaiting_classification."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.database import async_session_factory


async def main() -> None:
    async with async_session_factory() as s:
        result = await s.execute(
            text(
                """
                UPDATE invoices
                SET evaluation_status = 'vision_vaulted'
                WHERE evaluation_status = 'awaiting_classification'
                  AND (document_text IS NULL OR BTRIM(document_text) = '')
                  AND (document_type_code IS NULL OR BTRIM(document_type_code) = '')
                  AND document_heading IS NOT NULL
                  AND BTRIM(document_heading) <> ''
                  AND EXISTS (
                    SELECT 1 FROM audit_logs a
                    WHERE a.invoice_id = invoices.id
                      AND a.event = 'vision_path_pending'
                  )
                """
            )
        )
        await s.commit()
        print("updated", result.rowcount)


if __name__ == "__main__":
    asyncio.run(main())
