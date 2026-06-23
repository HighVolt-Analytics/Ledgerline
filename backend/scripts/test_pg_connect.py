"""Quick Postgres connectivity check using backend .env settings."""

from __future__ import annotations

import asyncio
import ssl
import sys

from app.azure_env import asyncpg_connect_args
from app.config import get_settings


async def main() -> int:
    settings = get_settings()
    host = settings.postgres_host
    print(f"host={host} db={settings.postgres_db} port={settings.postgres_port}")

    import asyncpg

    ssl_args = asyncpg_connect_args(settings.database_url)
    ssl_mode = ssl_args.get("ssl", "require")

    users = [
        settings.postgres_user,
        f"{settings.postgres_user}@{host.split('.')[0]}",
    ]
    seen: set[str] = set()
    for user in users:
        if user in seen:
            continue
        seen.add(user)
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=host,
                    port=settings.postgres_port,
                    database=settings.postgres_db,
                    user=user,
                    password=settings.postgres_password,
                    ssl=ssl_mode,
                ),
                timeout=20,
            )
            version = await conn.fetchval("SELECT version()")
            print(f"OK user={user!r} version={str(version)[:80]}")
            await conn.close()
            return 0
        except Exception as exc:
            print(f"FAIL user={user!r} {type(exc).__name__}: {exc}")

    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
