"""LLM-assisted sub-ledger assignment for invoice line items."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.audit.audit_service import log_event
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.llm_coa_catalogue import (
    build_line_sub_ledger_catalogue,
    parent_ledger_has_sub_ledger_catalogue,
)
from app.services.invoice.line_item_gl_service import (
    apply_sub_ledger_to_line,
    line_gl_mapping_applicable,
    resolve_doc_type_default_sub_ledger,
    resolve_parent_ledger,
    resolve_vendor_default_sub_ledger,
    validate_sub_ledger_for_parent,
)
from app.services.master_data.chart_of_accounts_service import sub_ledger_exists
from app.services.rule_book.account_mapper import resolve_category_for_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

_LINE_GL_SYSTEM = """You assign sub-ledgers to invoice line items for accounts payable.
The main GL account is FIXED — do not suggest a different parent ledger.
Return JSON only: {"line_suggestions": [{"line_index": 0, "sub_ledger": "", "confidence": 0.0, "reasoning": ""}]}

Rules:
- sub_ledger MUST be exactly one catalogue name or "" (empty string)
- empty sub_ledger means inherit the document-type or vendor default, or no segment
- one suggestion per line index provided
- homogeneous lines may share the same sub_ledger"""


def _fallback_sub_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    parent_ledger: str,
) -> tuple[str, str, str]:
    doc_default = resolve_doc_type_default_sub_ledger(invoice, config)
    if doc_default and sub_ledger_exists(parent_ledger, doc_default, config.chart_of_accounts):
        return doc_default, "doc_type_default", "Document type default sub-ledger"
    vendor_default = resolve_vendor_default_sub_ledger(
        invoice, config, parent_ledger=parent_ledger
    )
    if vendor_default and sub_ledger_exists(
        parent_ledger, vendor_default, config.chart_of_accounts
    ):
        return vendor_default, "vendor_default", "Vendor default sub-ledger"
    return "", "doc_type_default", "No sub-ledger segment — uses main ledger"


def _keyword_sub_ledger_hint(description: str, catalogue: list[dict[str, str]]) -> str:
    desc = (description or "").lower()
    if not desc:
        return ""
    for row in catalogue:
        name = row["name"]
        tokens = [token.strip().lower() for token in name.replace("—", " ").split() if token.strip()]
        for token in tokens:
            if len(token) >= 3 and token in desc:
                return name
    return ""


def _parse_llm_suggestions(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    rows = raw.get("line_suggestions")
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            cleaned.append(row)
    return cleaned


def _build_user_payload(
    *,
    parent_ledger: str,
    parent_code: str,
    catalogue: list[dict[str, str]],
    invoice: Invoice,
    doc_type_sub_ledger: str,
    vendor_sub_ledger: str,
) -> str:
    lines = []
    for index, line in enumerate(invoice.line_items):
        lines.append(
            {
                "line_index": index,
                "description": (line.description or "").strip(),
                "amount": str(line.amount) if line.amount is not None else "",
            }
        )
    payload = {
        "parent_ledger": parent_ledger,
        "parent_code": parent_code,
        "document_type_default_sub_ledger": doc_type_sub_ledger,
        "vendor_default_sub_ledger": vendor_sub_ledger,
        "sub_ledger_catalogue": catalogue,
        "line_items": lines,
    }
    return json.dumps(payload, default=str)


async def _llm_sub_ledger_suggestions(
    *,
    parent_ledger: str,
    parent_code: str,
    catalogue: list[dict[str, str]],
    invoice: Invoice,
    doc_type_sub_ledger: str,
    vendor_sub_ledger: str,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.line_gl_llm_available:
        return []
    user = _build_user_payload(
        parent_ledger=parent_ledger,
        parent_code=parent_code,
        catalogue=catalogue,
        invoice=invoice,
        doc_type_sub_ledger=doc_type_sub_ledger,
        vendor_sub_ledger=vendor_sub_ledger,
    )
    raw = await chat_json_async(
        system=_LINE_GL_SYSTEM,
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    return _parse_llm_suggestions(raw)


def _accept_llm_sub_ledger(
    candidate: str,
    confidence: float | None,
    *,
    parent_ledger: str,
    accounts: list,
    min_confidence: float,
) -> bool:
    if not candidate:
        return False
    if confidence is None or confidence < min_confidence:
        return False
    return validate_sub_ledger_for_parent(
        candidate,
        parent_ledger=parent_ledger,
        accounts=accounts,
    )


async def apply_line_gl_mapping(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """Assign sub-ledgers to line items under the document-type parent ledger."""
    if not line_gl_mapping_applicable(invoice, config):
        return False
    if not invoice.line_items:
        return False

    parent_ledger = resolve_parent_ledger(invoice, config)
    if not parent_ledger:
        return False

    if not parent_ledger_has_sub_ledger_catalogue(
        parent_ledger, config.chart_of_accounts
    ):
        for line in invoice.line_items:
            apply_sub_ledger_to_line(
                line,
                sub_ledger="",
                source="doc_type_default",
                reason="Main ledger has no sub-ledger catalogue",
            )
        return True

    catalogue = build_line_sub_ledger_catalogue(
        parent_ledger, config.chart_of_accounts
    )
    parent_code = resolve_category_for_config(parent_ledger, config).account_code
    doc_default = resolve_doc_type_default_sub_ledger(invoice, config)
    vendor_default = resolve_vendor_default_sub_ledger(
        invoice, config, parent_ledger=parent_ledger
    )

    suggestions = await _llm_sub_ledger_suggestions(
        parent_ledger=parent_ledger,
        parent_code=parent_code,
        catalogue=catalogue,
        invoice=invoice,
        doc_type_sub_ledger=doc_default,
        vendor_sub_ledger=vendor_default,
    )
    suggestion_by_index: dict[int, dict[str, Any]] = {}
    for row in suggestions:
        raw_index = row.get("line_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        suggestion_by_index[index] = row

    min_confidence = float(get_settings().runtime_llm_min_confidence)
    applied = 0
    for index, line in enumerate(invoice.line_items):
        row = suggestion_by_index.get(index)
        if row is not None:
            candidate = str(row.get("sub_ledger") or "").strip()
            confidence_raw = row.get("confidence")
            reasoning = str(row.get("reasoning") or "").strip()
            try:
                confidence = float(confidence_raw) if confidence_raw is not None else None
            except (TypeError, ValueError):
                confidence = None
            llm_confident = _accept_llm_sub_ledger(
                candidate,
                confidence,
                parent_ledger=parent_ledger,
                accounts=config.chart_of_accounts,
                min_confidence=min_confidence,
            )
            if llm_confident:
                apply_sub_ledger_to_line(
                    line,
                    sub_ledger=candidate,
                    source="llm",
                    confidence=confidence,
                    reason=reasoning or "LLM sub-ledger suggestion",
                )
                applied += 1
                continue
            if not candidate:
                fallback, source, reason = _fallback_sub_ledger(
                    invoice, config, parent_ledger=parent_ledger
                )
                apply_sub_ledger_to_line(
                    line,
                    sub_ledger=fallback,
                    source=source,
                    confidence=confidence,
                    reason=reasoning or reason,
                )
                applied += 1
                continue
            # Invalid or low-confidence LLM name → fall through to keyword/defaults.

        hint = _keyword_sub_ledger_hint(line.description or "", catalogue)
        if hint:
            apply_sub_ledger_to_line(
                line,
                sub_ledger=hint,
                source="keyword",
                reason=f"Description match: {hint}",
            )
            applied += 1
            continue

        fallback, source, reason = _fallback_sub_ledger(
            invoice, config, parent_ledger=parent_ledger
        )
        apply_sub_ledger_to_line(
            line,
            sub_ledger=fallback,
            source=source,
            reason=reason,
        )
        applied += 1

    await session.flush()
    await log_event(
        session,
        "line_gl_mapping_applied",
        invoice_id=invoice.id,
        detail={
            "parent_ledger": parent_ledger,
            "lines_mapped": applied,
            "llm_used": bool(suggestions),
        },
    )
    return applied > 0
