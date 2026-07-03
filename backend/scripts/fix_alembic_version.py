"""Reset alembic_version when DB points at a missing revision."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.database import async_session_factory


async def main(target: str) -> None:
    async with async_session_factory() as session:
        current = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        print(f"Current alembic_version: {current}")
        await session.execute(
            text("UPDATE alembic_version SET version_num = :v"),
            {"v": target},
        )
        await session.commit()
        updated = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        print(f"Updated alembic_version: {updated}")


if __name__ == "__main__":
    rev = sys.argv[1] if len(sys.argv) > 1 else "052"
    asyncio.run(main(rev))
