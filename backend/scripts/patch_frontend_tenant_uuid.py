"""Patch frontend tenant IDs to UUID strings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"

REPLACEMENTS = [
    ("tenant_id: number", "tenant_id: string"),
    ("id: number;\n  name: string;\n  slug: string;\n  currency", "id: string;\n  name: string;\n  slug: string;\n  currency"),
    ("PlatformTenantSummary {\n  id: number", "PlatformTenantSummary {\n  id: string"),
    ("tenantId: number", "tenantId: string"),
    ("tenant_id?: number", "tenant_id?: string"),
    ("org_id?: number", "org_id?: string"),
]

for path in ROOT.rglob("*.{ts,tsx}"):
    pass

for path in list(ROOT.rglob("*.ts")) + list(ROOT.rglob("*.tsx")):
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")
        print(path.relative_to(ROOT))
