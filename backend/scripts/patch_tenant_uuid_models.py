"""One-off patch: model tenant_id columns to UUID."""
import re
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / "app" / "models"

for path in MODELS.glob("*.py"):
    if path.name == "tenant.py":
        continue
    text = path.read_text(encoding="utf-8")
    if "tenant_id" not in text:
        continue
    original = text
    if "import uuid" not in text:
        if "from datetime import" in text:
            text = text.replace("from datetime import", "import uuid\nfrom datetime import", 1)
        elif "import enum" in text:
            text = text.replace("import enum", "import enum\nimport uuid", 1)
        else:
            text = "import uuid\n" + text
    if "Uuid" not in text:
        text = re.sub(
            r"(from sqlalchemy import )([^\n]+)",
            lambda m: m.group(1) + (m.group(2) + ", Uuid" if "Uuid" not in m.group(2) else m.group(2)),
            text,
            count=1,
        )
    text = text.replace(
        "tenant_id: Mapped[int | None] = mapped_column(\n        Integer,\n        ForeignKey(\"tenants.id\", ondelete=\"SET NULL\"),",
        "tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n        Uuid(as_uuid=True),\n        ForeignKey(\"tenants.id\", ondelete=\"SET NULL\"),",
    )
    text = re.sub(
        r"tenant_id: Mapped\[int\] = mapped_column\((ForeignKey\(\"tenants\.id\"[^)]*\)), index=True\)",
        r"tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), \1, index=True)",
        text,
    )
    text = re.sub(
        r"tenant_id: Mapped\[int\] = mapped_column\((ForeignKey\(\"tenants\.id\"[^)]*\))\)",
        r"tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), \1)",
        text,
    )
    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"updated {path.name}")
