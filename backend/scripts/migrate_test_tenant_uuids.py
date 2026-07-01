"""One-off: replace legacy integer tenant ids in tests with UUID constants."""

from __future__ import annotations

from pathlib import Path

IMPORT_LINE = "from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID\n"
REPLACEMENTS = [
    ("Tenant(id=2,", "Tenant(id=PLATFORM_TENANT_UUID,"),
    ("Tenant(id=1,", "Tenant(id=TESTING_TENANT_UUID,"),
    ("tenant_id=2", "tenant_id=PLATFORM_TENANT_UUID"),
    ("tenant_id=1", "tenant_id=TESTING_TENANT_UUID"),
    ("tenant_id: 2", "tenant_id: PLATFORM_TENANT_UUID"),
    ("tenant_id: 1", "tenant_id: TESTING_TENANT_UUID"),
]


def _insert_import(text: str) -> str:
    if "from app.tenant_ids import" in text:
        return text
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith('"""'):
        for i, line in enumerate(lines[1:], start=1):
            if line.strip().endswith('"""'):
                insert_at = i + 1
                break
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines.insert(insert_at, "\n" + IMPORT_LINE)
    return "".join(lines)


def main() -> None:
    tests = Path(__file__).resolve().parent.parent / "tests"
    changed: list[str] = []
    for path in sorted(tests.rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        orig = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if text == orig:
            continue
        if "TESTING_TENANT_UUID" in text or "PLATFORM_TENANT_UUID" in text:
            text = _insert_import(text)
        path.write_text(text, encoding="utf-8")
        changed.append(str(path.relative_to(tests.parent)))
    print(f"Updated {len(changed)} files")


if __name__ == "__main__":
    main()
