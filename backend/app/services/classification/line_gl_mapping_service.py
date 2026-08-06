"""LLM-assisted sub-ledger assignment under a fixed Document Type parent GL."""

from __future__ import annotations

import json
from collections import Counter
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
    _is_team_expense_invoice,
    apply_sub_ledger_to_line,
    line_gl_mapping_applicable,
    resolve_doc_type_default_sub_ledger,
    resolve_effective_ledger_mapping,
    resolve_parent_ledger,
    resolve_vendor_default_sub_ledger,
    validate_sub_ledger_for_parent,
)
from app.services.master_data.chart_of_accounts_service import sub_ledger_exists
from app.services.prompt_registry import resolve_system_prompt_text
from app.services.rule_book.account_mapper import resolve_category_for_config
from app.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_KEY = "llm.sub_ledger.assign.system"


def _fallback_sub_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    parent_ledger: str,
) -> tuple[str, str, str]:
    """Soft defaults only when they exist under the parent; else keep main GL ("")."""
    if not parent_ledger_has_sub_ledger_catalogue(
        parent_ledger, config.chart_of_accounts
    ):
        return "", "main_gl", "No sub-ledgers under parent — keep main GL"
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
    return "", "main_gl", "No matching sub-ledger — keep main GL"


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


def _parse_document_sub_ledger(raw: dict[str, Any] | None) -> tuple[str, float | None, str]:
    if not raw:
        return "", None, ""
    candidate = str(raw.get("document_sub_ledger") or "").strip()
    reasoning = str(raw.get("document_reasoning") or "").strip()
    confidence_raw = raw.get("document_confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    return candidate, confidence, reasoning


def _document_text_blob(invoice: Invoice) -> str:
    parts: list[str] = []
    heading = (getattr(invoice, "document_heading", None) or "").strip()
    if heading:
        parts.append(heading)
    text = (getattr(invoice, "document_text", None) or "").strip()
    if text:
        parts.append(text[:6000])
    vendor = (invoice.vendor or "").strip()
    if vendor:
        parts.append(f"vendor: {vendor}")
    return "\n".join(parts)


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
    for index, line in enumerate(invoice.line_items or []):
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
        "document_text": _document_text_blob(invoice),
        "document_heading": (getattr(invoice, "document_heading", None) or "").strip(),
        "route_target": (invoice.route_target or "").strip(),
        "team_expense_kind": (getattr(invoice, "team_expense_kind", None) or "").strip(),
        "document_type_code": (invoice.document_type_code or "").strip(),
    }
    return json.dumps(payload, default=str)


async def _llm_sub_ledger_assign(
    *,
    parent_ledger: str,
    parent_code: str,
    catalogue: list[dict[str, str]],
    invoice: Invoice,
    doc_type_sub_ledger: str,
    vendor_sub_ledger: str,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.line_gl_llm_available:
        return None
    user = _build_user_payload(
        parent_ledger=parent_ledger,
        parent_code=parent_code,
        catalogue=catalogue,
        invoice=invoice,
        doc_type_sub_ledger=doc_type_sub_ledger,
        vendor_sub_ledger=vendor_sub_ledger,
    )
    try:
        system = resolve_system_prompt_text(PROMPT_KEY)
    except KeyError:
        logger.warning("sub_ledger_prompt_missing", prompt_key=PROMPT_KEY)
        return None
    raw = await chat_json_async(
        system=system,
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    return raw if isinstance(raw, dict) else None


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


def _dominant_line_sub_ledger(invoice: Invoice) -> str:
    counts: Counter[str] = Counter()
    for line in invoice.line_items or []:
        sub = (getattr(line, "sub_ledger", None) or "").strip()
        if sub:
            counts[sub] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def _keep_main_gl_on_header(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    parent_ledger: str,
) -> None:
    """Header posts to parent GL when no Sub-GL was chosen."""
    parent_resolved = resolve_category_for_config(parent_ledger, config)
    invoice.account_name = parent_resolved.account_name or parent_ledger
    if parent_resolved.account_code:
        invoice.account_code = parent_resolved.account_code


def stamp_team_expense_header_sub_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    document_sub_ledger: str = "",
    document_confidence: float | None = None,
    document_reasoning: str = "",
) -> bool:
    """Stamp TE header to content Sub-GL; fall back to main (parent) GL when none."""
    if not _is_team_expense_invoice(invoice, config):
        return False

    parent_ledger = resolve_parent_ledger(invoice, config)
    if not parent_ledger:
        return False

    if not parent_ledger_has_sub_ledger_catalogue(
        parent_ledger, config.chart_of_accounts
    ):
        _keep_main_gl_on_header(invoice, config, parent_ledger=parent_ledger)
        return False

    min_confidence = float(get_settings().runtime_llm_min_confidence)
    candidate = (document_sub_ledger or "").strip()
    accepted = _accept_llm_sub_ledger(
        candidate,
        document_confidence,
        parent_ledger=parent_ledger,
        accounts=config.chart_of_accounts,
        min_confidence=min_confidence,
    )
    if not accepted:
        # Prefer dominant line Sub-GL when lines were mapped the same way.
        candidate = _dominant_line_sub_ledger(invoice)
        if not candidate or not validate_sub_ledger_for_parent(
            candidate,
            parent_ledger=parent_ledger,
            accounts=config.chart_of_accounts,
        ):
            hint = _keyword_sub_ledger_hint(
                _document_text_blob(invoice),
                build_line_sub_ledger_catalogue(
                    parent_ledger, config.chart_of_accounts
                ),
            )
            candidate = hint
        if not candidate:
            fallback, _source, _reason = _fallback_sub_ledger(
                invoice, config, parent_ledger=parent_ledger
            )
            candidate = fallback

    if not candidate or not validate_sub_ledger_for_parent(
        candidate,
        parent_ledger=parent_ledger,
        accounts=config.chart_of_accounts,
    ):
        _keep_main_gl_on_header(invoice, config, parent_ledger=parent_ledger)
        return False

    parent_resolved = resolve_category_for_config(parent_ledger, config)
    mapped = resolve_effective_ledger_mapping(
        parent_ledger=parent_ledger,
        effective_ledger=candidate,
        config=config,
    )
    invoice.account_name = mapped.account_name or candidate
    invoice.account_code = mapped.account_code or parent_resolved.account_code
    if document_reasoning:
        logger.info(
            "te_header_sub_ledger_stamped",
            invoice_id=invoice.id,
            parent_ledger=parent_ledger,
            sub_ledger=candidate,
            reason=document_reasoning,
        )
    return True


async def apply_line_gl_mapping(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """Assign Sub-GLs under the Document Type parent ledger (content-driven)."""
    if not line_gl_mapping_applicable(invoice, config):
        return False

    parent_ledger = resolve_parent_ledger(invoice, config)
    if not parent_ledger:
        return False

    is_te = _is_team_expense_invoice(invoice, config)
    has_lines = bool(invoice.line_items)

    if not parent_ledger_has_sub_ledger_catalogue(
        parent_ledger, config.chart_of_accounts
    ):
        # No children under main GL → every line + TE header keep parent (main GL).
        for line in invoice.line_items or []:
            apply_sub_ledger_to_line(
                line,
                sub_ledger="",
                source="main_gl",
                reason="No sub-ledgers under parent — keep main GL",
            )
        if is_te:
            _keep_main_gl_on_header(invoice, config, parent_ledger=parent_ledger)
        await session.flush()
        await log_event(
            session,
            "line_gl_mapping_applied",
            invoice_id=invoice.id,
            detail={
                "parent_ledger": parent_ledger,
                "lines_mapped": len(invoice.line_items or []),
                "llm_used": False,
                "prompt_key": PROMPT_KEY,
                "fallback": "main_gl",
                "had_lines": has_lines,
            },
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

    llm_raw = await _llm_sub_ledger_assign(
        parent_ledger=parent_ledger,
        parent_code=parent_code,
        catalogue=catalogue,
        invoice=invoice,
        doc_type_sub_ledger=doc_default,
        vendor_sub_ledger=vendor_default,
    )
    suggestions = _parse_llm_suggestions(llm_raw)
    doc_sub, doc_confidence, doc_reasoning = _parse_document_sub_ledger(llm_raw)

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
    # Same content → Sub-GL rules for every line under the fixed parent.
    for index, line in enumerate(invoice.line_items or []):
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

    header_stamped = False
    if is_te:
        header_stamped = stamp_team_expense_header_sub_ledger(
            invoice,
            config,
            document_sub_ledger=doc_sub,
            document_confidence=doc_confidence,
            document_reasoning=doc_reasoning,
        )

    await session.flush()
    await log_event(
        session,
        "line_gl_mapping_applied",
        invoice_id=invoice.id,
        detail={
            "parent_ledger": parent_ledger,
            "lines_mapped": applied,
            "llm_used": bool(llm_raw),
            "prompt_key": PROMPT_KEY,
            "team_expense_header_stamped": header_stamped,
            "document_sub_ledger": (invoice.account_name if header_stamped else doc_sub) or "",
            "had_lines": has_lines,
        },
    )
    return applied > 0 or header_stamped
