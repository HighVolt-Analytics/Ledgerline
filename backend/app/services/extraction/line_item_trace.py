"""Structured decision trace for invoice line-item extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.invoice.invoice_data import ParsedLineItem


@dataclass
class LineItemTrace:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        row_key: str,
        stage: str,
        action: str,
        reason: str,
        **extra: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "row_key": row_key,
            "stage": stage,
            "action": action,
            "reason": reason,
        }
        if extra:
            entry.update(extra)
        self.entries.append(entry)

    def to_dict(self) -> list[dict[str, Any]]:
        return list(self.entries)


class NoOpLineItemTrace(LineItemTrace):
    def record(
        self,
        row_key: str,
        stage: str,
        action: str,
        reason: str,
        **extra: Any,
    ) -> None:
        pass


def resolve_line_item_trace(enabled: bool) -> LineItemTrace:
    return LineItemTrace() if enabled else NoOpLineItemTrace()


def row_key_for_item(item: ParsedLineItem | None, index: int = 0) -> str:
    from app.services.extraction.line_items_parser import _normalize_line_description

    normalized = _normalize_line_description(item.description if item else None)
    if normalized:
        return normalized[:80]
    return f"row_{index}"


def active_trace(trace: LineItemTrace | None) -> LineItemTrace:
    return trace if trace is not None else NoOpLineItemTrace()
