"""Snapshot our invoice fields for adapters. Filled in a later stage (existing DB, no new extraction)."""

from __future__ import annotations

from typing import Any


def canonical_from_invoice(_invoice_id: int) -> dict[str, Any]:
    """Read existing invoice/lines/vendor/PDF when export is implemented."""
    raise NotImplementedError("canonical snapshot is not part of Stage 1")
