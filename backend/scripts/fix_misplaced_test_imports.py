"""Fix tenant id imports inserted inside functions by migrate_test_tenant_uuids.py."""

from __future__ import annotations

from pathlib import Path

IMPORT_LINE = "from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID\n"


def _top_level_import_index(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if line.startswith("from app.tenant_ids import"):
            return i
    return None


def _insert_after_header(lines: list[str]) -> list[str]:
    insert_at = 0
    if lines and lines[0].startswith('"""'):
        for i in range(1, min(len(lines), 30)):
            if lines[i].strip().endswith('"""'):
                insert_at = i + 1
                break
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at += 1
            continue
        break
    out = list(lines)
    out.insert(insert_at, "\n" + IMPORT_LINE)
    return out


def fix_file(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    first_def = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith(("def ", "class ", "async def ", "@pytest"))
        ),
        len(lines),
    )
    cleaned: list[str] = []
    seen_top_import = False
    removed = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("from app.tenant_ids import"):
            is_top_level = not line[: len(line) - len(stripped)]
            if is_top_level and not seen_top_import and i < first_def:
                seen_top_import = True
                cleaned.append(line)
            else:
                removed = True
            continue
        cleaned.append(line)

    if not removed:
        return False

    if not seen_top_import:
        cleaned = _insert_after_header(cleaned)

    path.write_text("".join(cleaned), encoding="utf-8")
    return True


def main() -> None:
    tests = Path(__file__).resolve().parent.parent / "tests"
    fixed = 0
    for path in sorted(tests.rglob("test_*.py")):
        if fix_file(path):
            fixed += 1
            print(path.relative_to(tests.parent))
    print(f"Fixed {fixed} files")


if __name__ == "__main__":
    main()
