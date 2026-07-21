"""Apply alembic revisions one at a time; stamp on duplicate-object failures.

Use when alembic_version was stamped to head without running all migrations,
leaving schema partially applied (e.g. missing 049 column but tables from 051+ exist).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def _revision_chain(from_rev: str, to_rev: str) -> list[str]:
    cfg = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    revs: list[str] = []
    cur = script.get_revision(to_rev)
    while cur and cur.revision != from_rev:
        revs.append(cur.revision)
        if cur.down_revision is None:
            break
        cur = script.get_revision(cur.down_revision)
    revs.reverse()
    return revs


def _current_revision() -> str | None:
    proc = subprocess.run(
        ["alembic", "current"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("INFO"):
            token = line.split()[0]
            if token and token[0].isdigit():
                return token
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    start = sys.argv[1] if len(sys.argv) > 1 else "048"
    head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    if head is None:
        print("ERROR: no alembic head revision found", file=sys.stderr)
        return 1

    chain = _revision_chain(start, head)
    print(f"repair: start={start!r} head={head!r} steps={len(chain)}")

    for rev in chain:
        current = _current_revision()
        if current == rev:
            print(f"skip {rev}: already at revision")
            continue
        if current and current > rev:
            print(f"skip {rev}: current {current} is ahead")
            continue

        print(f"upgrade -> {rev}")
        up = _run(["alembic", "upgrade", rev])
        if up.returncode == 0:
            print(f"ok {rev}")
            continue

        combined = (up.stdout or "") + (up.stderr or "")
        duplicate_markers = (
            "already exists",
            "DuplicateTableError",
            "DuplicateColumnError",
            "DuplicateObjectError",
        )
        if any(m in combined for m in duplicate_markers):
            print(f"stamp {rev}: duplicate object (schema already present)")
            stamp = _run(["alembic", "stamp", rev])
            if stamp.returncode != 0:
                print(stamp.stdout)
                print(stamp.stderr, file=sys.stderr)
                return stamp.returncode
            continue

        print(up.stdout)
        print(up.stderr, file=sys.stderr)
        return up.returncode

    final = _current_revision()
    print(f"done: alembic_version={final!r} expected={head!r}")
    return 0 if final == head else 1


if __name__ == "__main__":
    raise SystemExit(main())
