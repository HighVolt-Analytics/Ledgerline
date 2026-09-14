#!/usr/bin/env python3
"""Audit tenant document types that still depend on shipped DT-xx fallback data.

Phase 0 gate for the global document type dictionary migration. Run this alone
before removing v5DocumentTypes / document_type_defaults / classifier presets.

Usage:
  python -m scripts.audit_legacy_shipped_fallback_deps
  python -m scripts.audit_legacy_shipped_fallback_deps --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

from sqlalchemy import select

from app.database import async_session_factory
from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig

DT_MATRIX_RE = re.compile(r"^DT-\d+$", re.IGNORECASE)


def _token(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _list_field(row: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
    return []


def _classifier_children_empty(row: dict[str, Any]) -> bool:
    classifier = row.get("classifier")
    if not isinstance(classifier, dict):
        return True
    root = classifier.get("root")
    if not isinstance(root, dict):
        return True
    children = root.get("children")
    if not isinstance(children, list):
        return True
    return len(children) == 0


def _recognition_mode(row: dict[str, Any]) -> str:
    return _token(row, "recognition_mode", "recognitionMode").lower()


def _llm_prompt(row: dict[str, Any]) -> str:
    return _token(row, "llm_prompt", "llmPrompt")


def _analyze_document_type(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    org_code = _token(row, "code", "dt_code").upper()
    matrix_code = _token(row, "matrix_template_code", "matrixTemplateCode").upper()
    if not matrix_code or not DT_MATRIX_RE.match(matrix_code):
        return None

    extraction = _list_field(row, "extraction_fields", "extractionFields")
    playbook = _token(row, "playbook_profile", "playbookProfile").lower()
    classifier_empty = _classifier_children_empty(row)
    recognition = _recognition_mode(row)
    prompt = _llm_prompt(row)

    missing: list[str] = []
    if not extraction:
        missing.append("extraction_fields")
    if classifier_empty:
        missing.append("classifier.root.children")
    if not playbook:
        missing.append("playbook_profile")

    prompt_only_classifier_ok = (
        classifier_empty
        and recognition == "prompt"
        and bool(prompt)
        and missing == ["classifier.root.children"]
    )
    blocking_missing = [item for item in missing if item != "classifier.root.children"]
    blocking_dependent = bool(blocking_missing)
    dependent = bool(missing)

    return {
        "org_code": org_code,
        "matrix_template_code": matrix_code,
        "missing": missing,
        "blocking_missing": blocking_missing,
        "blocking_dependent": blocking_dependent,
        "dependent": dependent,
        "self_contained": not blocking_dependent,
        "recognition_mode": recognition or "signals",
        "has_llm_prompt": bool(prompt),
        "prompt_only_classifier_ok": prompt_only_classifier_ok,
    }


def _summarize_tenant(
    tenant_id: str,
    tenant_name: str,
    document_types: list[Any],
) -> dict[str, Any]:
    legacy_rows: list[dict[str, Any]] = []
    blocking_dependents: list[dict[str, Any]] = []
    prompt_only_gaps: list[dict[str, Any]] = []
    self_contained: list[dict[str, Any]] = []

    for raw in document_types:
        if not isinstance(raw, dict):
            continue
        analyzed = _analyze_document_type(raw)
        if analyzed is None:
            continue
        legacy_rows.append(analyzed)
        row = {**analyzed, "tenant_id": tenant_id, "tenant_name": tenant_name}
        if analyzed["blocking_dependent"]:
            blocking_dependents.append(row)
        elif analyzed.get("prompt_only_classifier_ok"):
            prompt_only_gaps.append(row)
        else:
            self_contained.append(row)

    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "legacy_matrix_rows": len(legacy_rows),
        "blocking_dependents": blocking_dependents,
        "prompt_only_classifier_gaps": prompt_only_gaps,
        "self_contained_legacy": self_contained,
    }


async def audit() -> dict[str, Any]:
    tenant_summaries: list[dict[str, Any]] = []
    all_blocking: list[dict[str, Any]] = []
    all_prompt_gaps: list[dict[str, Any]] = []
    all_self_contained: list[dict[str, Any]] = []
    all_legacy = 0

    async with async_session_factory() as session:
        tenants = (await session.execute(select(Tenant).order_by(Tenant.name.asc()))).scalars().all()
        configs = (await session.execute(select(TenantRuleBookConfig))).scalars().all()
        config_by_tenant = {row.tenant_id: row for row in configs}
        tenant_by_id = {row.id: row for row in tenants}

        for tenant_id, cfg_row in config_by_tenant.items():
            tenant = tenant_by_id.get(tenant_id)
            tenant_name = (tenant.name if tenant else "") or ""
            config = cfg_row.config if isinstance(cfg_row.config, dict) else {}
            document_types = config.get("document_types") or config.get("documentTypes") or []
            if not isinstance(document_types, list):
                document_types = []
            summary = _summarize_tenant(str(tenant_id), tenant_name, document_types)
            tenant_summaries.append(summary)
            all_blocking.extend(summary["blocking_dependents"])
            all_prompt_gaps.extend(summary["prompt_only_classifier_gaps"])
            all_self_contained.extend(summary["self_contained_legacy"])
            all_legacy += summary["legacy_matrix_rows"]

    return {
        "blocking_dependents": len(all_blocking),
        "prompt_only_classifier_gaps": len(all_prompt_gaps),
        "self_contained_legacy": len(all_self_contained) + len(all_prompt_gaps),
        "legacy_matrix_rows_total": all_legacy,
        "tenants_scanned": len(tenant_summaries),
        "blocking_rows": all_blocking,
        "prompt_only_rows": all_prompt_gaps,
        "self_contained_rows": all_self_contained,
        "tenant_summaries": tenant_summaries,
        "legacy_safety_net_required": len(all_blocking) > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    args = parser.parse_args()

    result = asyncio.run(audit())

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"blocking_dependents: {result['blocking_dependents']}")
    print(f"prompt_only_classifier_gaps: {result['prompt_only_classifier_gaps']}")
    print(f"self_contained_legacy: {result['self_contained_legacy']}")
    print(f"legacy_matrix_rows_total: {result['legacy_matrix_rows_total']}")
    print(f"tenants_scanned: {result['tenants_scanned']}")
    print(f"legacy_safety_net_required: {result['legacy_safety_net_required']}")
    print()

    if result["blocking_rows"]:
        print("Blocking dependent rows (missing extraction/playbook — need fallback or backfill):")
        for row in result["blocking_rows"]:
            missing = ", ".join(row.get("blocking_missing") or [])
            print(
                f"  tenant={row.get('tenant_id')} org={row.get('org_code')} "
                f"matrix={row.get('matrix_template_code')} missing=[{missing}]"
            )
    else:
        print("No blocking dependents — safe to proceed without a legacy safety net.")

    if result["prompt_only_rows"]:
        print()
        print("Non-blocking: prompt-mode rows with empty classifier only:")
        for row in result["prompt_only_rows"]:
            print(
                f"  tenant={row.get('tenant_id')} org={row.get('org_code')} "
                f"matrix={row.get('matrix_template_code')}"
            )


if __name__ == "__main__":
    main()
