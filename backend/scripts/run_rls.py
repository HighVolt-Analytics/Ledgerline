"""Apply tenant RLS SQL script using sync psycopg."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        from app.config import get_settings

        url = get_settings().database_url
    url = (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = None
    if "ssl" in query:
        sslmode = query.pop("ssl", ["require"])[0]
    if "sslmode" in query:
        sslmode = query.pop("sslmode", [sslmode or "require"])[0]
    new_query = urlencode({k: v[0] for k, v in query.items()})
    base = urlunparse(parsed._replace(query=new_query))
    if sslmode:
        sep = "&" if new_query else "?"
        return f"{base}{sep}sslmode={sslmode}"
    return base


def main() -> int:
    sql_path = Path(__file__).resolve().parent / "apply_tenant_rls.sql"
    sql = sql_path.read_text(encoding="utf-8")
    with psycopg.connect(_sync_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("RLS policies applied successfully.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
