"""Validate alembic_version before `alembic upgrade head` in CI/deploy.

Never stamps to head — that skips migrations and causes schema drift.
If the stored revision is unknown, fail loudly so operators run
`scripts/repair_alembic_upgrade.py` (incremental upgrade + stamp on duplicates).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session_factory


def _known_revisions() -> set[str]:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    return {rev.revision for rev in script.walk_revisions()}


def _head_revision() -> str:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected single alembic head, found: {heads}")
    return heads[0]


async def main() -> None:
    known = _known_revisions()
    head = _head_revision()

    async with async_session_factory() as session:
        current = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        print(f"alembic_version={current!r} codebase_head={head!r}")

        if current in known:
            print("alembic_version_ok")
            return

        if current is None:
            print(
                "ERROR: alembic_version is empty. Run `alembic upgrade head` on a fresh database "
                "or `python scripts/repair_alembic_upgrade.py <base>` for partial schema."
            )
            raise SystemExit(1)

        print(
            f"ERROR: unknown alembic revision {current!r}. "
            "Do not stamp to head — run `python scripts/repair_alembic_upgrade.py` instead."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
