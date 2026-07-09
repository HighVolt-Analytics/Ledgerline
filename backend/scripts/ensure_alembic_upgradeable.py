"""Ensure alembic_version points at a revision that exists in this codebase.

Use before `alembic upgrade head` in CI/staging when a phantom revision (e.g. 060)
was stamped manually but never merged to the repo.
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
            await session.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": head},
            )
            await session.commit()
            print(f"inserted alembic_version={head}")
            return

        print(f"repairing unknown revision {current!r} -> {head!r}")
        await session.execute(
            text("UPDATE alembic_version SET version_num = :v"),
            {"v": head},
        )
        await session.commit()
        print("alembic_version_repaired")


if __name__ == "__main__":
    asyncio.run(main())
