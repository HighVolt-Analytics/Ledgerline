#!/usr/bin/env python3
"""Inventory tenant document_ai_provider settings (explicit or env default).

Usage:
  python -m scripts.tenant_ai_provider_inventory
  python -m scripts.tenant_ai_provider_inventory --json
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.extraction.document_ai_provider import DocumentAiProvider


async def inventory() -> list[dict[str, str]]:
    default_provider = get_settings().default_document_ai_provider
    rows: list[dict[str, str]] = []

    async with async_session_factory() as session:
        tenants = (await session.execute(select(Tenant).order_by(Tenant.name.asc()))).scalars().all()
        configs = (
            await session.execute(select(TenantRuleBookConfig))
        ).scalars().all()
        config_by_tenant = {row.tenant_id: row for row in configs}

    for tenant in tenants:
        cfg_row = config_by_tenant.get(tenant.id)
        explicit: str | None = None
        source = "env_default"
        if cfg_row and isinstance(cfg_row.config, dict):
            try:
                payload = RuleBookConfigPayload.model_validate(cfg_row.config)
                ai_cfg = payload.ai_classification
                if ai_cfg is not None and (ai_cfg.document_ai_provider or "").strip():
                    explicit = ai_cfg.document_ai_provider.strip()
                    source = "tenant_rule_book"
            except Exception:
                raw_ai = cfg_row.config.get("ai_classification") or cfg_row.config.get("aiClassification")
                if isinstance(raw_ai, dict):
                    token = raw_ai.get("document_ai_provider") or raw_ai.get("documentAiProvider")
                    if isinstance(token, str) and token.strip():
                        explicit = token.strip()
                        source = "tenant_rule_book_raw"

        resolved = DocumentAiProvider.from_config(explicit or default_provider).value
        rows.append(
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name or "",
                "explicit_provider": explicit or "",
                "resolved_provider": resolved,
                "source": source,
                "env_default": default_provider,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = asyncio.run(inventory())

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    if not rows:
        print("(no tenants)")
        return

    columns = ["tenant_id", "tenant_name", "resolved_provider", "explicit_provider", "source"]
    widths = {col: max(len(col), *(len(str(row.get(col, ""))) for row in rows)) for col in columns}
    print(" | ".join(col.ljust(widths[col]) for col in columns))
    print("-+-".join("-" * widths[col] for col in columns))
    for row in rows:
        print(" | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns))

    foundry = sum(1 for row in rows if row["resolved_provider"] == DocumentAiProvider.AZURE_FOUNDRY_VISION.value)
    gemini = sum(1 for row in rows if row["resolved_provider"] == DocumentAiProvider.GEMINI_VISION.value)
    azure_di = sum(1 for row in rows if row["resolved_provider"] == DocumentAiProvider.AZURE_DI.value)
    print(
        f"\nSummary: total={len(rows)} "
        f"foundry={foundry} gemini={gemini} azure_di={azure_di} "
        f"env_default={get_settings().default_document_ai_provider}"
    )


if __name__ == "__main__":
    main()
